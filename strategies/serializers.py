from rest_framework import serializers
from .models import TradingStrategy, DynamicLevel

class DynamicLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = DynamicLevel
        fields = ['level_number', 'price', 'lot_size']

class TradingStrategySerializer(serializers.ModelSerializer):
    levels = DynamicLevelSerializer(many=True, read_only=True)

    class Meta:
        model = TradingStrategy
        fields = ['id', 'base_price', 'percentage_change', 'api_key', 'api_secret', 'trading_symbol', 'is_running', 'start_time', 'end_time', 'levels']
