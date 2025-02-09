from django.urls import path

from strategies.views import StrategyBuySell, PlaceBuySellOrders
from .views import CustomerRegisterView, CustomerLoginView, CustomerLogoutView, HomeView, PlaceOrderView, \
    PriceQuantityAPIView, StopStrategy, KillActionView, OauthLogin, CallBackLoginUrl, GetTableDataAPIView, \
    GetDynamicFieldsAPIView

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('register/', CustomerRegisterView.as_view(), name='register'),
    path('login/', CustomerLoginView.as_view(), name='login'),
    path('logout/', CustomerLogoutView.as_view(), name='logout'),
    path('start_strategy/', PlaceOrderView.as_view(), name='start_strategy'),
    path('add_table/', PriceQuantityAPIView.as_view(), name='add_table'),
    path('modify_strategy_parameters/', StopStrategy.as_view(), name='modify_strategy_parameters'),

    # Skip kill pause buttons
    path('sell_order/', KillActionView.as_view(), name='sell_order'),

    # Oauth related URLS
    path('oauth_login/', OauthLogin.as_view(), name='oauth_login'),
    path('fyers_login/', CallBackLoginUrl.as_view(), name='fyers_login'),

    path('api/static-data/', GetTableDataAPIView.as_view(), name='static_data_api'),
    path('api/dynamic-data/', GetDynamicFieldsAPIView.as_view(), name='dynamic_data_api'),
    path('strategy_buy_sell/', StrategyBuySell.as_view(), name='strategy_buy_sell'),
    path('api/buy_sell/', PlaceBuySellOrders.as_view(), name='buy_sell'),


]
