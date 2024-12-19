import json

from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from rest_framework import serializers
from .models import Customer, PriceQuantityTable
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError

from rest_framework import serializers
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError

from rest_framework.exceptions import ValidationError


class CustomerRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['phone_number', 'email', 'name', 'password']

    def validate_phone_number(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Phone number must contain only digits.")
        if len(value) != 10:  # Assuming a standard 10-digit phone number.
            raise serializers.ValidationError("Phone number must be 10 digits long.")
        return value

    def validate_email(self, value):
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return value

    def validate(self, attrs):
        # You can customize the order of validation
        if Customer.objects.filter(phone_number=attrs['phone_number']).exists():
            raise serializers.ValidationError({"phone_number": "A customer with this phone number already exists."})

        if Customer.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"email": "A customer with this email already exists."})

        return attrs

    def create(self, validated_data):
        customer = Customer(
            phone_number=validated_data.get('phone_number'),
            email=validated_data.get('email'),
            name=validated_data.get('name')
        )
        customer.set_password(validated_data.get('password'))
        customer.save()
        return customer


class CustomerLoginSerializer(serializers.Serializer):
    email_or_phone = serializers.CharField()
    password = serializers.CharField()

    def validate(self, data):
        email_or_phone = data.get('email_or_phone')
        password = data.get('password')

        # Check if user provided email or phone
        if '@' in email_or_phone:
            customer = Customer.objects.filter(email=email_or_phone).first()
        else:
            customer = Customer.objects.filter(phone_number=email_or_phone).first()

        # Validate credentials
        if customer and customer.check_password(password):
            return customer
        raise serializers.ValidationError("Invalid email/phone number or password.")


class PriceQuantitySerializer(serializers.ModelSerializer):
    price_quantity_data = serializers.JSONField()

    class Meta:
        model = PriceQuantityTable
        fields = ['name', 'price_quantity_data']

    def create(self, validated_data):
        print('validated data', validated_data)
        # Save the dictionary as a JSON string in the model
        validated_data['price_quantity_data'] = json.dumps(validated_data['price_quantity_data'])
        return super().create(validated_data)
