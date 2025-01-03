import logging
import shlex
import subprocess
import time
import uuid
from typing import Any

from typing_extensions import Self

from swerex import PACKAGE_NAME, REMOTE_EXECUTABLE_NAME
from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import DockerDeploymentConfig
from swerex.deployment.hooks.abstract import CombinedDeploymentHook, DeploymentHook
from swerex.exceptions import DeploymentNotStartedError, DockerPullError
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.config import RemoteRuntimeConfig
from swerex.runtime.remote import RemoteRuntime
from swerex.utils.free_port import find_free_port
from swerex.utils.log import get_logger
from swerex.utils.wait import _wait_until_alive

__all__ = ["DockerDeployment", "DockerDeploymentConfig"]


def _is_image_available(image: str) -> bool:
    try:
        subprocess.check_call(["docker", "inspect", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def _pull_image(image: str) -> bytes:
    try:
        return subprocess.check_output(["docker", "pull", image], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        # e.stderr contains the error message as bytes
        raise subprocess.CalledProcessError(e.returncode, e.cmd, e.output, e.stderr) from None


def _remove_image(image: str) -> bytes:
    return subprocess.check_output(["docker", "rmi", image], timeout=30)


class DockerDeployment(AbstractDeployment):
    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        """Deployment to local docker image.

        Args:
            **kwargs: Keyword arguments (see `DockerDeploymentConfig` for details).
        """
        self._config = DockerDeploymentConfig(**kwargs)
        self._runtime: RemoteRuntime | None = None
        self._container_process = None
        self._container_name = None
        self.logger = logger or get_logger("rex-deploy")
        self._runtime_timeout = 0.15
        self._hooks = CombinedDeploymentHook()

    def add_hook(self, hook: DeploymentHook):
        self._hooks.add_hook(hook)

    @classmethod
    def from_config(cls, config: DockerDeploymentConfig) -> Self:
        return cls(**config.model_dump())

    def _get_container_name(self) -> str:
        """Returns a unique container name based on the image name."""
        image_name_sanitized = "".join(c for c in self._config.image if c.isalnum() or c in "-_.")
        return f"{image_name_sanitized}-{uuid.uuid4()}"

    @property
    def container_name(self) -> str | None:
        return self._container_name

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive. The return value can be
        tested with bool().

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            msg = "Runtime not started"
            raise RuntimeError(msg)
        if self._container_process is None:
            msg = "Container process not started"
            raise RuntimeError(msg)
        if self._container_process.poll() is not None:
            msg = "Container process terminated."
            output = "stdout:\n" + self._container_process.stdout.read().decode()  # type: ignore
            output += "\nstderr:\n" + self._container_process.stderr.read().decode()  # type: ignore
            msg += "\n" + output
            raise RuntimeError(msg)
        return await self._runtime.is_alive(timeout=timeout)

    async def _wait_until_alive(self, timeout: float = 10.0):
        try:
            return await _wait_until_alive(self.is_alive, timeout=timeout, function_timeout=self._runtime_timeout)
        except TimeoutError as e:
            self.logger.error("Runtime did not start within timeout. Here's the output from the container process.")
            self.logger.error(self._container_process.stdout.read().decode())  # type: ignore
            self.logger.error(self._container_process.stderr.read().decode())  # type: ignore
            assert self._container_process is not None
            await self.stop()
            raise e

    def _get_token(self) -> str:
        return str(uuid.uuid4())

    def _get_swerex_start_cmd(self, token: str) -> list[str]:
        rex_args = f"--auth-token {token}"
        pipx_install = "python3 -m pip install pipx && python3 -m pipx ensurepath"
        # Need to wrap with /bin/sh -c to avoid having '&&' interpreted by the parent shell
        return [
            "/bin/sh",
            # "-l",
            "-c",
            f"{REMOTE_EXECUTABLE_NAME} {rex_args} || ({pipx_install} && pipx run {PACKAGE_NAME} {rex_args})",
        ]

    def _pull_image(self) -> None:
        if self._config.pull == "never":
            return
        if self._config.pull == "missing" and _is_image_available(self._config.image):
            return
        self.logger.info(f"Pulling image {self._config.image!r}")
        self._hooks.on_custom_step("Pulling docker image")
        try:
            _pull_image(self._config.image)
        except subprocess.CalledProcessError as e:
            msg = f"Failed to pull image {self._config.image}"
            raise DockerPullError(msg) from e

    async def start(self):
        """Starts the runtime."""
        self._pull_image()
        if self._config.port is None:
            self._config.port = find_free_port()
        assert self._container_name is None
        self._container_name = self._get_container_name()
        token = self._get_token()
        cmds = [
            "docker",
            "run",
            "--rm",
            "-p",
            f"{self._config.port}:8000",
            *self._config.docker_args,
            "--name",
            self._container_name,
            self._config.image,
            *self._get_swerex_start_cmd(token),
        ]
        cmd_str = shlex.join(cmds)
        self.logger.info(
            f"Starting container {self._container_name} with image {self._config.image} serving on port {self._config.port}"
        )
        self.logger.debug(f"Command: {cmd_str!r}")
        # shell=True required for && etc.
        self._container_process = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._hooks.on_custom_step("Starting runtime")
        self.logger.info(f"Starting runtime at {self._config.port}")
        self._runtime = RemoteRuntime.from_config(
            RemoteRuntimeConfig(port=self._config.port, timeout=self._runtime_timeout, auth_token=token)
        )
        t0 = time.time()
        await self._wait_until_alive(timeout=self._config.startup_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    async def stop(self):
        """Stops the runtime."""
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

        if self._container_process is not None:
            try:
                subprocess.check_call(
                    ["docker", "kill", self._container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                self.logger.warning(f"Failed to kill container {self._container_name}: {e}", exc_info=True)
            for _ in range(3):
                self._container_process.kill()
                try:
                    self._container_process.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            else:
                self.logger.warning(f"Failed to kill container {self._container_name} with SIGKILL")

            self._container_process = None
            self._container_name = None

        if self._config.remove_images:
            if _is_image_available(self._config.image):
                self.logger.info(f"Removing image {self._config.image}")
                try:
                    _remove_image(self._config.image)
                except subprocess.CalledProcessError:
                    self.logger.error(f"Failed to remove image {self._config.image}", exc_info=True)

    @property
    def runtime(self) -> RemoteRuntime:
        """Returns the runtime if running.

        Raises:
            DeploymentNotStartedError: If the deployment was not started.
        """
        if self._runtime is None:
            raise DeploymentNotStartedError()
        return self._runtime
