#!/usr/bin/python3

import utils
import subprocess, shutil, os, traceback

class Config :

	def __init__(self, swarm, api) :
		self.__swarm = swarm
		self.__api = api

	def global(self, instances) :
		try :
			for instance_id, instance in instances.items() :
				env = instance.attrs["Spec"]["TaskTemplate"]["ContainerSpec"]["Env"]
				break
			vars
			for var_value in env :
				var = var_value.split("=")[0]
				value = var_value.replace(var + "=", "", 1)
				vars[var] = value
			proc = subprocess.run(["/opt/entrypoint/global-config"], vars["SERVER_NAME"]], env=vars, capture_output=True)
			return proc.returncode == 0
		except Exception as e :
			traceback.print_exc()
			utils.log("[!] Error while generating config : " + str(e))
		return False

	def generate(self, instances, vars) :
		try :
			# Get env vars from bunkerized-nginx instances
			vars_instances = {}
			for instance_id, instance in instances.items() :
				if self.__swarm :
					env = instance.attrs["Spec"]["TaskTemplate"]["ContainerSpec"]["Env"]
				else :
					env = instance.attrs["Config"]["Env"]
				for var_value in env :
					var = var_value.split("=")[0]
					value = var_value.replace(var + "=", "", 1)
					vars_instances[var] = value
			vars_defaults = vars.copy()
			vars_defaults.update(vars_instances)
			vars_defaults.update(vars)
			# Call site-config.sh to generate the config
			proc = subprocess.run(["/opt/entrypoint/site-config.sh", vars["SERVER_NAME"]], env=vars_defaults, capture_output=True)
			if proc.returncode == 0 :
				proc = subprocess.run(["/opt/entrypoint/multisite-config.sh"], capture_output=True)
				return proc.returncode == 0
		except Exception as e :
			traceback.print_exc()
			utils.log("[!] Error while generating config : " + str(e))
		return False

	def activate(self, instances, vars) :
		try :
			# Check if file exists
			if not os.path.isfile("/etc/nginx/" + vars["SERVER_NAME"] + "/server.conf") :
				utils.log("[!] /etc/nginx/" + vars["SERVER_NAME"] + "/server.conf doesn't exist")
				return False

			# Include the server conf
			utils.replace_in_file("/etc/nginx/nginx.conf", "}", "include /etc/nginx/" + vars["SERVER_NAME"] + "/server.conf;\n}")

			return self.reload(instances)
		except Exception as e :
			utils.log("[!] Error while activating config : " + str(e))
		return False

	def deactivate(self, instances, vars) :
		try :
			# Check if file exists
			if not os.path.isfile("/etc/nginx/" + vars["SERVER_NAME"] + "/server.conf") :
				utils.log("[!] /etc/nginx/" + vars["SERVER_NAME"] + "/server.conf doesn't exist")
				return False

			# Remove the include
			utils.replace_in_file("/etc/nginx/nginx.conf", "include /etc/nginx/" + vars["SERVER_NAME"] + "/server.conf;\n", "")

			return self.reload(instances)

		except Exception as e :
			utils.log("[!] Error while deactivating config : " + str(e))
		return False

	def remove(self, instances, vars) :
		try :
			# Check if file exists
			if not os.path.isfile("/etc/nginx/" + vars["SERVER_NAME"] + "/server.conf") :
				utils.log("[!] /etc/nginx/" + vars["SERVER_NAME"] + "/server.conf doesn't exist")
				return False

			# Remove the folder
			shutil.rmtree("/etc/nginx/" + vars["SERVER_NAME"])
			return True
		except Exception as e :
			utils.log("[!] Error while deactivating config : " + str(e))
		return False

	def reload(self, instances) :
		ret = True
		for instance_id, instance in instances.items() :
			# Reload the instance object just in case
			instance.reload()
			# Reload via API
			if self.__swarm :
				# Send POST request on http://serviceName.NodeID.TaskID:8000/reload
				name = instance.name
				for task in instance.tasks() :
					nodeID = task["NodeID"]
					taskID = task["ID"]
					fqdn = name + "." + nodeID + "." + taskID
					req = requests.post("http://" + fqdn + ":8080" + api + "/reload")
					if req and req.status_code == 200 :
						utils.log("[*] Sent reload order to instance " + fqdn + " (service.node.task)")
					else :
						utils.log("[!] Can't reload : API error for instance " + fqdn + " (service.node.task)")
						ret = False
			# Send SIGHUP to running instance
			elif instance.status == "running" :
				try :
					instance.kill("SIGHUP")
					utils.log("[*] Sent SIGHUP signal to bunkerized-nginx instance " + instance.name + " / " + instance.id)
				except docker.errors.APIError as e :
					utils.log("[!] Docker error while sending SIGHUP signal : " + str(e))
					ret = False
		return ret