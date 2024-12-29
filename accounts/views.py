import json
import threading

from django.contrib import messages
from django.db import transaction
from django.db.models import F, Window, Sum, OuterRef, Subquery
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, redirect
from fyers_apiv3 import fyersModel
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import OrderStrategyForm, OrderLevelForm
from .main_strategy import TradingStrategy1
from .models import PriceQuantityTable, OrderStrategy, Orders, OrderLevel, AccessToken
from .serializers import CustomerLoginSerializer
from .serializers import CustomerRegistrationSerializer
from .strategy_handler import StrategyManager
from .utils import get_balance, get_customer, get_instrument, create_table, get_lot_size, get_access_token, client_id, secret_key, redirect_uri, access_token, InvalidStrikeDirectionError, ExpiryNotFoundError, OptionChainDataError


class CustomerRegisterView(APIView):
    def get(self, request):
        return render(request, 'register.html')

    def post(self, request):
        serializer = CustomerRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            messages.success(request, 'Registration successful')
            return redirect('login')
        else:
            # Pass errors and form data back to the template
            return render(request, 'register.html', {
                'errors': serializer.errors,  # Pass errors
                'data': request.data  # Pass form data to keep user input
            })


class CustomerLoginView(APIView):
    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
        serializer = CustomerLoginSerializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
            customer = serializer.validated_data  # This will be the validated Customer object

            # Manually set the session for the customer
            request.session['customer_id'] = customer.id  # Store customer ID in session

            messages.success(request, 'Logged in successfully')
            return redirect('home')
        except ValidationError as e:
            return render(request, 'login.html', {
                'errors': serializer.errors,
                'data': request.data
            })
        except Exception as e:
            messages.error(request, "Unexpected error: " + str(e))
            return redirect('login')


class CustomerLogoutView(APIView):
    def get(self, request):
        # Clear the customer ID from the session
        if 'customer_id' in request.session:
            del request.session['customer_id']

        messages.success(request, 'Logged out successfully')  # Add a success message
        return redirect('login')


class HomeView(APIView):

    def get(self, request):
        customer = get_customer(request)
        strategy_manager = StrategyManager()

        active_strategies=strategy_manager.list_active_strategies()
        strategies = OrderStrategy.objects.filter(id__in=active_strategies)
        # strategies = OrderStrategy.objects.filter(id__in=[25])

        strategy_forms = []

        # Create forms for each strategy and its levels
        for strategy in strategies:
            strategy_form = OrderStrategyForm(instance=strategy)
            level_forms = [
                OrderLevelForm(instance=level, prefix=f"level-{level.id}")
                for level in strategy.order_levels.all()
            ]

            strategy_forms.append({
                'strategy_form': strategy_form,
                'level_forms': level_forms,
                'strategy_id': strategy.id,

            })

        return render(request, 'home.html', {
            'strategy_forms': strategy_forms,
            'customer': customer,
        })

    def post(self, request):
        strategy_id = request.POST.get('strategy_id')
        strategy = OrderStrategy.objects.get(id=strategy_id)
        # Process forms
        strategy_form = OrderStrategyForm(request.POST, instance=strategy)
        if strategy_form.is_valid():
            strategy_form.save()

        for level in strategy.order_levels.all():
            level_form = OrderLevelForm(
                request.POST, instance=level, prefix=f"level-{level.id}"
            )
            if level_form.is_valid():
                level_form.save()

        return self.get(request)  # Re-render the page

class PlaceOrderView(APIView):
    template_name = 'place_order.html'

    def get(self, request):
        customer = get_customer(request)
        total_balance, utilised_balance, realised_profit_loss, limit_at_start_of_day, available_balance = get_balance(
            request)

        tables = PriceQuantityTable.objects.filter(is_active=True)
        table_options = {}

        for key, table in enumerate(tables):
            data = json.loads(table.price_quantity_data)

            profit = []
            loss = []

            for level_data in data.values():
                if 'price' in level_data:
                    price = level_data['price']
                    if price > 0:
                        profit.append(('price', price))
                    elif price < 0:
                        loss.append(('price', price))

            table_options[f'Table {key + 1}'] = {
                'profit': profit,
                'loss': loss,
                'name': table.name,
                'id': table.id,
            }
        access_token = get_access_token()
        strike_distance = reversed(range(-7, 8))
        return render(request, self.template_name, {
            'customer': customer,  # Pass the customer to the template
            'table_options': table_options,
            "strike_distance": strike_distance,
            "total_balance": total_balance,
            "utilised_balance": utilised_balance,
            "realised_profit_loss": realised_profit_loss,
            "limit_at_start_of_day": limit_at_start_of_day,
            "available_balance": available_balance,
            "access_token": access_token
        })

    def post(self, request):
        """
        Handles the POST request for initiating a trading strategy.

        Validates user input, fetches required data, creates strategy and table records,
        and starts the trading strategy in a separate thread.
        """
        # Retrieve customer based on the request
        customer = get_customer(request)
        if customer is None:
            return render(request, 'login.html')

        data = request.POST
        try:
            # Validate and retrieve input fields
            index = data.get("indexSelect")
            strike_direction = data.get("strikeDirection")
            strike_distance = int(data.get("strikeDistance"))  # Ensured as integer
            trade_mode = data.get("tradeMode")
            transaction_type = data.get("transactionType")
            order_type = data.get("orderType")
            target = float(data.get("profitTarget"))  # Ensure target is a float
            limit_price = int(data.get("limitPrice")) if data.get("limitPrice") else None
            quantity = int(data.get("quantity"))  # Ensure quantity is integer
            expiry = data.get("expiry", "")  # Default expiry to 0 if not provided
            table_id = int(data.get("selected_table"))
            hedging = data.get("isHedging")

            # Ensure all hedging-related fields are validated
            hedging_strike_distance = int(data.get("hedgeStrikeDistance"))
            hedging_quantity = int(data.get("hedgingQuantity"))
            hedging_limit_quantity = int(data.get("hedgingLimitQuantity"))
            hedging_limit_price = float(data.get("hedgingLimitPercentage"))
            limit_order_change_time = int(data.get("HedgingTimeToChangeOrder"))

            # Determine hedging strike direction
            hedging_strike_direction = 'call' if strike_direction == 'put' else 'put'

            # Fetch lot size and instrument details
            lot_size = get_lot_size(index)
            instrument_symbol, instrument_price = get_instrument(index, expiry, strike_distance, strike_direction)

            # Fetch hedging instrument details
            hedging_instrument_symbol, hedging_instrument_price = get_instrument(
                index, expiry, hedging_strike_distance, hedging_strike_direction
            )
            # Determine main price for the trade
            main_price = limit_price if limit_price else instrument_price

            # Create strategy and table records within a transaction
            with transaction.atomic():
                strategy = OrderStrategy.objects.create(
                    user=customer,
                    main_instrument=instrument_symbol,
                    is_hedging=True if hedging == 'on' else False,
                    original_price=main_price,
                    hedging_instrument=hedging_instrument_symbol,
                    hedging_strike_distance=hedging_strike_distance,
                    hedging_quantity=hedging_quantity,
                    hedging_limit_price=(1 - hedging_limit_price/100) * main_price,
                    hedging_limit_quantity=hedging_limit_quantity,
                    hedge_limit_order_time_for_convert_from_lo_to_mo=limit_order_change_time
                )

                # Fetch the selected table and create associated entries
                data_table = PriceQuantityTable.objects.get(id=table_id)
                create_table(
                    main_price, target, strategy, hedging_limit_price, quantity=quantity,
                    table=data_table, hedging_quantity=hedging_quantity,
                    hedging_limit_quantity=hedging_limit_quantity
                )

            # Start the trading strategy in a separate thread
            token = get_access_token()
            strategy_parameters = {
                "strategy": strategy,
                "access_token": token,
                "data_table": data_table,
                "target": target,
                "hedging_limit_price": hedging_limit_price,
                "strike_distance": strike_distance,
                "strike_direction": strike_direction,
                "hedging_strike_distance": hedging_strike_distance,
                "hedging_strike_direction": hedging_strike_direction,
                "index": index,
                "expiry": expiry,
            }
            strategy_manager = StrategyManager()

            # Start a couple of strategies
            strategy_manager.start_strategy(
                strategy_id=strategy.id,
                strategy_class=TradingStrategy1,
                strategy_parameters=strategy_parameters,
            )

            # Log success and redirect
            messages.success(request, f"Strategy started Successfully..")
            return redirect('start_strategy')

        except ValueError as ve:
            # Handle invalid numeric inputs
            messages.error(request, f"Invalid input: {ve}")
            return redirect('start_strategy')

        except PriceQuantityTable.DoesNotExist:

            # Handle table not found error
            messages.error(request, "The selected Price Quantity Table does not exist.")
            return redirect('start_strategy')
        except InvalidStrikeDirectionError as e:

            messages.error(request, f"Strike direction is invalid: {e}")
            return redirect('start_strategy')
        except ExpiryNotFoundError as e:

            messages.error(request, f"Expiry date is not found: {e}")
            return redirect('start_strategy')
        except OptionChainDataError as e:

            messages.error(request, f"Option chain not found: {e}")
            return redirect('start_strategy')

        except Exception as e:

            # Handle any unexpected errors
            messages.error(request, f"An unexpected error occurred. Please try again. {e}")
            return redirect('start_strategy')


class StopStrategy(APIView):
    def get(self, request):
        strategy = OrderStrategy.objects.filter(is_active=True)
        levels = OrderLevel.objects.filter(strategy__in=strategy)
        active_orders = Orders.objects.filter(level__in=levels, entry_order_id__isnull=False)

        return render(request, 'modify_strategy.html', {'strategies': strategy, "active_orders": active_orders})

    def post(self, request):
        strategy = request.POST.get('strategy')

        # Trigger Celery task to stop the strategy
        # stop_trading_strategy.delay(strategy)

        return redirect('home')


class PriceQuantityAPIView(APIView):

    def get(self, request):
        return render(request, 'create_table.html')

    def post(self, request, *args, **kwargs):
        try:
            # Retrieve form data
            required_fields = [
                'main_percentage[]', 'main_quantity[]', 'hedge_percentage[]',
                'hedge_quantity[]', 'hedge_market_quantity[]', 'main_target[]'
            ]
            form_data = {field: request.POST.getlist(field) for field in required_fields}
            name = request.POST.get('name')

            # Basic validation
            if not name:
                messages.error(request, 'Name is required')
                return render(request, 'create_table.html', {'error': 'Name field is required.'}, status=400)

            total_entries = len(form_data['main_percentage[]'])
            if not all(len(lst) == total_entries for lst in form_data.values()):
                messages.error(request, 'All input lists must have the same number of entries.')
                return render(request, 'create_table.html', {'error': 'Please fill all values in the row'}, status=400)

            # Constructing the JSON object
            values_data = {}
            for i in range(total_entries):
                try:
                    values_data[str(i + 1)] = {
                        'main_percentage': float(form_data['main_percentage[]'][i]),
                        'main_quantity': int(form_data['main_quantity[]'][i]),
                        'hedge_percentage': float(form_data['hedge_percentage[]'][i]),
                        'hedge_limit_quantity': int(form_data['hedge_quantity[]'][i]),
                        'hedge_market_quantity': int(form_data['hedge_market_quantity[]'][i]),
                        'main_target': float(form_data['main_target[]'][i]),
                    }
                except (ValueError, TypeError) as e:
                    messages.error(request, f"Form data is invalid {i + 1}")
                    return render(request, 'create_table.html', {
                        'error': f'Invalid data format at entry {i + 1}: {str(e)}'
                    }, status=400)

            # Save to model
            PriceQuantityTable.objects.create(
                name=name,
                price_quantity_data=json.dumps(values_data)
            )
            messages.success(request, "Table created successfully")
            return render(request, 'create_table.html', {'message': 'Data saved successfully!'}, status=201)

        except Exception as e:
            messages.error(request, "Unexpected error occurred. Please fill the table again")
            return render(request, 'create_table.html', {'error': f'An unexpected error occurred: {str(e)}'}, status=500)


class SkipActionView(APIView):
    def get(self, request, id):
        # Perform the skip action here
        return Response({"message": f"Skip action triggered for ID: {id}"}, status=status.HTTP_200_OK)


class KillActionView(APIView):
    def get(self, request, id):
        print('sell order triggered', id)
        # Perform the kill action here
        return


class PauseCallActionView(APIView):
    def get(self, request, id):
        # Perform the kill action here
        return Response({"message": f"Kill action triggered for ID: {id}"}, status=status.HTTP_200_OK)


class PausePutActionView(APIView):
    def get(self, request, id):
        # Perform the kill action here
        return Response({"message": f"Kill action triggered for ID: {id}"}, status=status.HTTP_200_OK)


class KillHedgingActionView(APIView):
    def get(self, request, id):
        # Perform the kill action here
        return Response({"message": f"Kill action triggered for ID: {id}"}, status=status.HTTP_200_OK)


class PauseHedgingActionView(APIView):
    def get(self, request, id):
        # Perform the kill action here
        return Response({"message": f"Kill action triggered for ID: {id}"}, status=status.HTTP_200_OK)


class OauthLogin(APIView):
    def get(self, request):
        return render(request, 'oauth_login.html', context={})

    def post(self, request):
        api_key = request.data.get('api_key')
        api_secret = request.data.get('api_secret')

        if not api_key or not api_secret:
            return HttpResponseBadRequest("API Key and API Secret are required.")

        # Generate the URL to redirect to
        target_url = f"https://api-t1.fyers.in/api/v3/generate-authcode?client_id={client_id}&redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Ffyers_login&response_type=code&state=sample"

        # Redirect to the generated URL
        return redirect(target_url)


class CallBackLoginUrl(APIView):
    def get(self, request):
        auth_code = request.GET.get('auth_code')
        if auth_code:
            session = fyersModel.SessionModel(
                client_id=client_id,
                secret_key=secret_key,
                redirect_uri=redirect_uri,
                response_type="code",
                grant_type="authorization_code"
            )

            # Set the authorization code in the session object
            session.set_token(auth_code)

            # Generate the access token using the authorization code
            response = session.generate_token()
            if "access_token" in response:
                AccessToken.objects.create(access_token=response["access_token"], is_active=True)
                messages.success(request, "The Oauth Token has been generated")
                return redirect('home')
            else:
                messages.error(request, "Oauth Code not received. Please Try again")
                return redirect('/oauth_login')
        else:
            messages.error(request, "Oauth Code not received. Please Try again")
            return redirect('/oauth_login')


class GetTableDataAPIView(APIView):
    def get(self, request, *args, **kwargs):
        strategy_id = kwargs.get('strategy_id')
        if not strategy_id:
            return Response({"error": "Strategy ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Subquery to get the entry price for the main trade
        main_trade_entry_price = (
            Orders.objects.filter(
                level=OuterRef('id'),
                is_entry=True,
                is_complete=False,
            )
            .values('entry_price')[:1]  # Select only the first matching order
        )

        # Subquery to get the entry price for the hedging trade
        hedging_trade_entry_price = (
            Orders.objects.filter(
                level=OuterRef('id'),
                is_entry=True,
                is_complete=False,
            )
            .exclude(is_main=True)
            .values('entry_price')[:1]  # Select only the first matching order
        )

        levels = OrderLevel.objects.filter(strategy_id=strategy_id).annotate(
        # Calculate the cumulative sum of main_quantity for previous levels
        cumulative_quantity=Window(
            expression=Sum('main_quantity'),
            order_by=F('id').asc()
        ),
        # Calculate the product of main_price and main_quantity
        value=F('main_percentage') * F('main_quantity'),
        # Entry price for main trade
        main_trade_entry_price=Subquery(main_trade_entry_price),
        # Entry price for hedging trade
        hedging_trade_entry_price=Subquery(hedging_trade_entry_price),
    ).values(
            'id', 'main_percentage', 'main_quantity', 'main_target', 'hedging_quantity', 'cumulative_quantity', 'value', 'main_trade_entry_price', 'hedging_trade_entry_price'
        )
        return Response(list(levels), status=status.HTTP_200_OK)


class GetDynamicFieldsAPIView(APIView):
    def get(self, request, *args, **kwargs):
        strategy_id = request.GET.get('strategy_id')
        if not strategy_id:
            return Response({"error": "Strategy ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        strategy = OrderStrategy.objects.get(id=strategy_id)
        data = {
            "symbols": f"{strategy.main_instrument},{strategy.hedging_instrument}"
        }
        fyers = fyersModel.FyersModel(client_id=client_id, token=access_token, is_async=False, log_path="")
        response = fyers.quotes(data=data)

        try:
            orders = Orders.objects.filter(level__strategy=strategy, is_entry=True, is_complete=False)

            data = {}
            for order in orders:
                if order.is_main:
                    data[order.level.id] = {
                        "price": (response['d'][0]['v']['ask'] - float(order.entry_price)) * order.level.main_quantity,
                        "order_id": order.id,  # Assuming 'order.id' contains the main order ID
                        "hedging_order_id": getattr(order, 'hedging_order_id', None)  # Safely get 'hedging_order_id'
                    }
        except Exception as ex:
            print('exception ', ex)
        return Response(data, status=status.HTTP_200_OK)