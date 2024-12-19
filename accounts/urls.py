from django.urls import path

from .views import CustomerRegisterView, CustomerLoginView, CustomerLogoutView, HomeView, PlaceOrderView, \
    PriceQuantityAPIView, StopStrategy, SkipActionView, KillActionView, PauseCallActionView, PausePutActionView, KillHedgingActionView, PauseHedgingActionView, OauthLogin, CallBackLoginUrl, GetTableDataAPIView, \
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
    path('skip/<int:id>/', SkipActionView.as_view(), name='your_skip_endpoint'),
    path('sell_order/<int:id>/', KillActionView.as_view(), name='sell_order'),
    path('pause-call/<int:id>/', PauseCallActionView.as_view(), name='your_pause_call_endpoint'),
    path('pause-put/<int:id>/', PausePutActionView.as_view(), name='your_pause_put_endpoint'),
    path('kill-hedging/<int:id>/', KillHedgingActionView.as_view(), name='your_kill_hedging_endpoint'),
    path('pause-hedging/<int:id>/', PauseHedgingActionView.as_view(), name='your_pause_hedging_endpoint'),

    # Oauth related URLS
    path('oauth_login/', OauthLogin.as_view(), name='oauth_login'),
    path('fyers_login/', CallBackLoginUrl.as_view(), name='fyers_login'),

    path('api/get_table_data/<int:strategy_id>/', GetTableDataAPIView.as_view(), name='get_table_data'),
    path('api/get_dynamic_fields/', GetDynamicFieldsAPIView.as_view(), name='get_dynamic_fields'),

]
