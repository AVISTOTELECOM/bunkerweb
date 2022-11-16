from kubernetes import client as kube_client
from os.path import exists
from subprocess import run
from typing import Any, Union

from API import API
from ApiCaller import ApiCaller


class Instance:
    _id: str
    name: str
    hostname: str
    _type: str
    health: bool
    env: Any
    apiCaller: ApiCaller

    def __init__(
        self,
        _id: str,
        name: str,
        hostname: str,
        _type: str,
        status: str,
        data: Any = None,
        apiCaller: ApiCaller = ApiCaller(),
    ) -> None:
        self._id = _id
        self.name = name
        self.hostname = hostname
        self._type = _type
        self.health = status == "up" and (
            (
                data.attrs["State"]["Health"]["Status"] == "healthy"
                if "Health" in data.attrs["State"]
                else False
            )
            if _type == "container" and data
            else True
        )
        self.env = data
        self.apiCaller = apiCaller

    def get_id(self) -> str:
        return self._id

    def reload(self) -> bool:
        return self.apiCaller._send_to_apis("POST", "/reload")

    def start(self) -> bool:
        return self.apiCaller._send_to_apis("POST", "/start")

    def stop(self) -> bool:
        return self.apiCaller._send_to_apis("POST", "/stop")

    def restart(self) -> bool:
        return self.apiCaller._send_to_apis("POST", "/restart")


class Instances:
    def __init__(self, docker_client, integration: str):
        self.__docker = docker_client
        self.__integration = integration

    def __instance_from_id(self, _id) -> Instance:
        instances: list[Instance] = self.get_instances()
        for instance in instances:
            if instance._id == _id:
                return instance

        raise Exception(f"Can't find instance with id {_id}")

    def get_instances(self) -> list[Instance]:
        instances = []
        # Docker instances (containers or services)
        if self.__docker is not None:
            for instance in self.__docker.containers.list(
                all=True, filters={"label": "bunkerweb.INSTANCE"}
            ):
                env_variables = {
                    x[0]: x[1]
                    for x in [env.split("=") for env in instance.attrs["Config"]["Env"]]
                }

                apiCaller = ApiCaller()
                apiCaller._set_apis(
                    [
                        API(
                            f"http://{instance.name}:{env_variables.get('API_HTTP_PORT', '5000')}",
                            env_variables.get("API_SERVER_NAME", "bwapi"),
                        )
                    ]
                )

                instances.append(
                    Instance(
                        instance.id,
                        instance.name,
                        instance.name,
                        "container",
                        "up" if instance.status == "running" else "down",
                        instance,
                        apiCaller,
                    )
                )
        elif self.__integration == "Swarm":
            for instance in self.__docker.services.list(
                filters={"label": "bunkerweb.INSTANCE"}
            ):
                status = "down"
                desired_tasks = instance.attrs["ServiceStatus"]["DesiredTasks"]
                running_tasks = instance.attrs["ServiceStatus"]["RunningTasks"]
                if desired_tasks > 0 and (desired_tasks == running_tasks):
                    status = "up"

                instances.append(
                    Instance(
                        instance.id,
                        instance.name,
                        instance.name,
                        "service",
                        status,
                        instance,
                        apiCaller,
                    )
                )
        elif self.__integration == "Kubernetes":
            corev1 = kube_client.CoreV1Api()
            for pod in corev1.list_pod_for_all_namespaces(watch=False).items:
                if (
                    pod.metadata.annotations != None
                    and "bunkerweb.io/INSTANCE" in pod.metadata.annotations
                ):
                    env_variables = {
                        e.name: e.value for e in pod.spec.containers[0].env
                    }

                    apiCaller = ApiCaller()
                    apiCaller._set_apis(
                        [
                            API(
                                f"http://{pod.status.pod_ip}:{env_variables.get('API_HTTP_PORT', '5000')}",
                                env_variables.get("API_SERVER_NAME", "bwapi"),
                            )
                        ]
                    )

                    status = "up"
                    if pod.status.conditions is not None:
                        for condition in pod.status.conditions:
                            if condition.type == "Ready" and condition.status == "True":
                                status = "down"
                                break

                    instances.append(
                        Instance(
                            pod.metadata.uid,
                            pod.metadata.name,
                            pod.status.pod_ip,
                            "pod",
                            status,
                            pod,
                            apiCaller,
                        )
                    )

        instances = sorted(
            instances,
            key=lambda x: x.name,
        )

        # Local instance
        if exists("/usr/sbin/nginx"):
            instances.insert(
                0,
                Instance(
                    "local",
                    "local",
                    "127.0.0.1",
                    "local",
                    "up" if exists("/var/tmp/bunkerweb/nginx.pid") else "down",
                ),
            )

        return instances

    def send_custom_configs_to_instances(self) -> Union[list[str], str]:
        failed_to_send: list[str] = []
        for instance in self.get_instances():
            if instance.health is False:
                failed_to_send.append(instance.name)
                continue

            if not instance.send_custom_configs():
                failed_to_send.append(instance.name)

        return failed_to_send or "Successfully sent custom configs to instances"

    def reload_instances(self) -> Union[list[str], str]:
        not_reloaded: list[str] = []
        for instance in self.get_instances():
            if instance.health is False:
                not_reloaded.append(instance.name)
                continue

            if self.reload_instance(instance=instance).startswith("Can't reload"):
                not_reloaded.append(instance.name)

        return not_reloaded or "Successfully reloaded instances"

    def reload_instance(self, id: int = None, instance: Instance = None) -> str:
        if instance is None:
            instance = self.__instance_from_id(id)

        result = True
        if instance._type == "local":
            result = (
                run(
                    ["sudo", "systemctl", "restart", "bunkerweb"], capture_output=True
                ).returncode
                != 0
            )
        elif instance._type == "container":
            # result = instance.run_jobs()
            result = result & instance.reload()

        if result:
            return f"Instance {instance.name} has been reloaded."

        return f"Can't reload {instance.name}"

    def start_instance(self, id) -> str:
        instance = self.__instance_from_id(id)
        result = True

        if instance._type == "local":
            proc = run(
                ["sudo", "/usr/share/bunkerweb/ui/linux.sh", "start"],
                capture_output=True,
            )
            result = proc.returncode == 0
        elif instance._type == "container":
            result = instance.start()

        if result:
            return f"Instance {instance.name} has been started."

        return f"Can't start {instance.name}"

    def stop_instance(self, id) -> str:
        instance = self.__instance_from_id(id)
        result = True

        if instance._type == "local":
            proc = run(
                ["sudo", "/usr/share/bunkerweb/ui/linux.sh", "stop"],
                capture_output=True,
            )
            result = proc.returncode == 0
        elif instance._type == "container":
            result = instance.stop()

        if result:
            return f"Instance {instance.name} has been stopped."

        return f"Can't stop {instance.name}"

    def restart_instance(self, id) -> str:
        instance = self.__instance_from_id(id)
        result = True

        if instance._type == "local":
            proc = run(
                ["sudo", "/usr/share/bunkerweb/ui/linux.sh", "restart"],
                capture_output=True,
            )
            result = proc.returncode == 0
        elif instance._type == "container":
            result = instance.restart()

        if result:
            return f"Instance {instance.name} has been restarted."

        return f"Can't restart {instance.name}"