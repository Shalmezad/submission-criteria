FROM python:3.6
# Create a seperate directory:
RUN mkdir /submission-criteria
WORKDIR /submission-criteria

# Set up and install our requirements:
ADD requirements.txt /submission-criteria/requirements.txt
RUN pip install -r requirements.txt
