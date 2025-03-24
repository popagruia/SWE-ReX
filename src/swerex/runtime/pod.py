
import logging
from abc import ABC, abstractmethod
from swerex.runtime.abstract import AbstractRuntime

class PodRuntime(AbstractRuntime):
    def close(self):
        # Implementation to close the pod
        self.logger.info('Closing pod runtime')

    def close_session(self):
        # Implementation to close the session
        self.logger.info('Closing session in pod runtime')

    def create_session(self):
        # Implementation to create a session
        self.logger.info('Creating session in pod runtime')

    def execute(self):
        # Implementation to execute commands
        self.logger.info('Executing command in pod runtime')

    def is_alive(self):
        # Implementation to check if the runtime is alive
        self.logger.info('Checking if pod runtime is alive')
        return True

    def read_file(self):
        # Implementation to read a file
        self.logger.info('Reading file from pod runtime')

    def run_in_session(self):
        # Implementation to run commands in session
        self.logger.info('Running command in session in pod runtime')

    def upload(self):
        # Implementation to upload files
        self.logger.info('Uploading file to pod runtime')

    def write_file(self):
        # Implementation to write files
        self.logger.info('Writing file to pod runtime')
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def run_pod(self, pod_name, namespace, sandboxed_image, container_port, service_port):
        # Using kubernetes client to run the pod
        from kubernetes import client, config
        config.load_kube_config()
        core_v1 = client.CoreV1Api()

        # Define the sandboxed Pod specification
        sandboxed_pod = client.V1Pod()
        sandboxed_pod.api_version = "v1"
        sandboxed_pod.kind = "Pod"
        sandboxed_pod.metadata = client.V1ObjectMeta(name=pod_name, namespace=namespace, labels={"app": pod_name}) # Add label

        sandboxed_container = client.V1Container(name="sandboxed-container", image=sandboxed_image, ports=[client.V1ContainerPort(container_port=container_port)])

        sandboxed_pod.spec = client.V1PodSpec(
            containers=[sandboxed_container],
            runtime_class_name="kata-fc" # Ensure correct runtime class name
        )

        # Create the sandboxed Pod
        core_v1.create_namespaced_pod(namespace=namespace, body=sandboxed_pod)

        # Define the Service specification
        service = client.V1Service()
        service.api_version = "v1"
        service.kind = "Service"
        service.metadata = client.V1ObjectMeta(name=f"{pod_name}-service", namespace=namespace)

        service.spec = client.V1ServiceSpec(
            selector={"app": pod_name}, # Select the pod by label
            ports=[client.V1ServicePort(protocol="TCP", port=service_port, target_port=container_port)]
        )

        # Create the Service
        core_v1.create_namespaced_service(namespace=namespace, body=service)

        self.logger.info("Pod and service created successfully.")
        return True, "Sandboxed Pod and Service created successfully"

