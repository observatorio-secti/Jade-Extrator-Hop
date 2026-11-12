FROM apache/hop:latest

USER root

COPY --chown=hop:hop . /files/jade-extrator

RUN mkdir -p /files/jade-extrator/logs/executions \
    && chown -R hop:hop /files/jade-extrator \
    && chmod -R u+rwX /files/jade-extrator \
    && chmod +x /files/jade-extrator/scripts/prune-logs.sh

ENV HOP_CUSTOM_ENTRYPOINT_EXTENSION_SHELL_FILE_PATH=/files/jade-extrator/scripts/prune-logs.sh

USER hop
