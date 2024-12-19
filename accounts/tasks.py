# accounts/tasks.py
from celery import shared_task
from .models import OrderStrategy  # Import your StrategyObject model
from .strategy import TradingStrategy  # Import your TradingStrategy class

@shared_task(bind=True)
def run_trading_strategy(self, strategy_id, access_token):

    """Celery task to run the trading strategy."""
    try:
        strategy = OrderStrategy.objects.get(id=strategy_id)  # Fetch your strategy instance
        trading_strategy = TradingStrategy(strategy, access_token)
        trading_strategy.run_strategy()
    except Exception as e:
        print(f"Error running strategy {strategy_id}: {e}")
        # You might want to log this or raise an alert
