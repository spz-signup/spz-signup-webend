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
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends fonts-dejavu gcc libc-dev git gpg libmagic1 libpq-dev postgresql-client xz-utils && \
    pip install -U pip setuptools --no-cache-dir && \
    rm -rf /root/.cache /var/cache/*
    
# Check and downgrade pip if necessary
RUN pip --version && \
    pip install --upgrade "pip<24.1" && \
    pip --version

# install python requirements and do cleanup
COPY requirements.txt requirements.txt
RUN pip install -U -r requirements.txt --no-cache-dir && \
    rm -rf /root/.cache /var/cache/*
# TODO: uninstall build-only requirements (gcc, git, ...)

# create state directory
RUN mkdir /state && \
    chown -R spz:spz /state

# copy code & config
COPY --chown=spz:spz uwsgi.ini uwsgi.ini
COPY --chown=spz:spz src/spz spz

# switch to spz user
USER 1000

# build assets
RUN python -m spz.setup.build_assets

# expose port
EXPOSE 3031

# set default startup command
CMD ["uwsgi --ini uwsgi.ini"]
