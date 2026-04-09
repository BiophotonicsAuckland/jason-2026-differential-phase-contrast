FROM ubuntu:22.04

# Avoid prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
COPY ./lib/ /tmp/lib/

ARG USERNAME=ws
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update

RUN apt-get install -y \
    python3.10 \
    python3.10-venv \
    libusb-1.0-0 \
    libavcodec58 \
    libavformat58 \
    libswscale5 \
    libswresample3 \
    libavutil56 \
    qtbase5-dev \
    qtchooser \
    qt5-qmake \
    qtbase5-dev-tools \
    # python3.10-dev \
    sudo \
    curl

# Delete user if it exists in container (e.g Ubuntu Noble: ubuntu)
RUN if id -u $USER_UID ; then userdel `id -un $USER_UID` ; fi

# Create the user
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    # [Optional] Add sudo support. Omit if you don't need to install software after connecting.
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

RUN cd /tmp/lib/spinnaker-4.3.0.189-amd64 \
    && printf "yes\nno\nno\n"| sudo sh /tmp/lib/spinnaker-4.3.0.189-amd64/install_spinnaker.sh

RUN python3 -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install \
        numpy==1.23 \
        matplotlib \
        pyqt5 \
        /tmp/lib/spinnaker-4.3.0.189-amd64/spinnaker_python-4.3.0.189-cp310-cp310-linux_x86_64.whl

# CMD ["/bin/sh", "-c"]
USER $USERNAME
SHELL ["/bin/bash", "-c"]
