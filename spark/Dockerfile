FROM bitnami/spark:latest

# 필요 시 pip와 기본 툴 설치
USER root

WORKDIR /opt/spark-app

# 파이썬 의존성 설치
#COPY spark/requirements.txt /tmp/
#RUN apt-get update && apt-get install -y python3-pip
#RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY spark/requirements.txt /opt/spark-app/
RUN apt-get update && apt-get install -y python3-pip
RUN pip install --no-cache-dir -r requirements.txt

# 작업 디렉토리 복사 (streaming_consumer.py 및 shared/ 폴더 포함)
#COPY spark /opt/spark-app/spark
#COPY shared /opt/spark-app/shared
COPY ./spark/streaming_consumer.py /opt/spark-app/
COPY ./shared /opt/spark-app/shared

#ENV PYTHONPATH=/opt/spark-app
#WORKDIR /opt/spark-app/spark
