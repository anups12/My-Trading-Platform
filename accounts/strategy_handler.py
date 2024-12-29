import threading

class StrategyManager:

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(StrategyManager, cls).__new__(cls, *args, **kwargs)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self):
        if not self.__initialized:
            self.strategies = {}
            self.lock = threading.Lock()
            self.__initialized = True


    def start_strategy(self, strategy_id: str, strategy_class, strategy_parameters: dict):
        with self.lock:
            if strategy_id in self.strategies:
                raise ValueError(f"Strategy with ID {strategy_id} is already running.")

            # Create strategy instance
            strategy_instance = strategy_class(strategy_parameters)
            thread = threading.Thread(target=strategy_instance.run_strategy, daemon=True)

            # Start the thread
            thread.start()

            # Store in the dictionary
            self.strategies[strategy_id] = {
                "thread": thread,
                "instance": strategy_instance,
            }
        print('strategies', self.strategies)

    def stop_strategy(self, strategy_id: str):
        with self.lock:
            if strategy_id not in self.strategies:
                raise ValueError(f"No strategy with ID {strategy_id} found.")

            # Access the instance and stop it
            strategy_instance = self.strategies[strategy_id]["instance"]
            strategy_instance.is_active = False

            # Wait for the thread to terminate
            thread = self.strategies[strategy_id]["thread"]
            thread.join(timeout=5)  # Wait a max of 5 seconds for clean exit

            # Remove from tracking
            del self.strategies[strategy_id]

    def list_active_strategies(self):
        with self.lock:
            return list(self.strategies.keys())

    def get_strategy_status(self, strategy_id: str):
        with self.lock:
            if strategy_id not in self.strategies:
                return {"status": "not found"}

            strategy_instance = self.strategies[strategy_id]["instance"]
            return {
                "is_active": strategy_instance.is_active,
                "parameters": strategy_instance.strategy_parameters,
            }
