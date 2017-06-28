FROM python:3
MAINTAINER https://github.com/SatelliteQE

RUN mkdir nailgun
COPY / /root/nailgun
RUN cd /root/nailgun && python3 setup.py install

ENV HOME /root/nailgun
WORKDIR /root/nailgun

CMD ["python"]
