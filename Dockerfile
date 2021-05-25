# base information
FROM python:3.9-slim
MAINTAINER KIT Sprachenzentrum

# create user
RUN useradd --home-dir /home/spz --create-home --shell /bin/bash --uid 1000 spz

# set workdir
WORKDIR /home/spz/code

# upgrade system and install requirements (normal and build)
RUN apt-get update && \
    mkdir -p /usr/share/man/man1 && \
    mkdir -p /usr/share/man/man7 && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get install -y fonts-dejavu gcc git gpg libmagic1 libpq-dev postgresql-client xz-utils && \
    pip install -U pip setuptools --no-cache-dir && \
    rm -rf /root/.cache /var/cache/*

# install requirements and do cleanup
COPY requirements.txt /home/spz/code/requirements.txt
RUN pip install -U -r requirements.txt --no-cache-dir && \
    rm -rf /root/.cache /var/cache/*

# copy code
COPY ./src/spz /home/spz/code/spz
RUN mkdir /state && \
    chown -R spz:spz /home/spz/code /state

# copy config
RUN mkdir /home/spz/config
COPY ./uwsgi.ini uwsgi.ini

# security and volumes
VOLUME ["/home/spz/code/spz/static", "/state"]
USER 1000

# expose port
EXPOSE 3031

# set default startup command
CMD ["uwsgi --ini uwsgi.ini"]
