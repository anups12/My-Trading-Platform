# Dockerfile

# Use an official Python runtime as the base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Install SSH client to clone from GitHub
RUN apt-get update && \
    apt-get install -y openssh-client git

# Accept the SSH_PRIVATE_KEY build argument
ARG SSH_PRIVATE_KEY

# Copy your SSH private key into the container (be careful with this step)
RUN mkdir -p ~/.ssh && \
    echo "$SSH_PRIVATE_KEY" > ~/.ssh/id_rsa && \
    chmod 600 ~/.ssh/id_rsa

# Disable host key checking (since we are using SSH)
RUN touch ~/.ssh/known_hosts && \
    ssh-keyscan github.com >> ~/.ssh/known_hosts

# Clone the private repository
RUN git clone git@github.com:your-username/your-private-repo.git .

# Copy the requirements.txt file and install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Expose the Django app port
EXPOSE 8000

# Set the command to run the Django application
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
