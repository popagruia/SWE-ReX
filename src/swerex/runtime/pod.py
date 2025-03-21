
import logging
from abc import ABC, abstractmethod
from swerex.runtime.abstract import AbstractRuntime

class PodRuntime(AbstractRuntime):
    def close(self):
        pass

    def close_session(self):
        pass

    def create_session(self):
        pass

    def execute(self):
        pass

    def is_alive(self):
        pass

    def read_file(self):
        pass

    def run_in_session(self):
        pass

    def upload(self):
        pass

    def write_file(self):
        pass
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def run_pod(self, pod_spec):
        self.logger.info("Running pod with spec: %s", pod_spec)
        # Using kubernetes client to run the pod
        from kubernetes import client, config
        config.load_kube_config()
        v1 = client.CoreV1Api()
        resp = v1.create_namespaced_pod(
            body=pod_spec,
            namespace='default')
        self.logger.info("Pod created. status='%s'", resp.status.phase)
        return resp
        pass
