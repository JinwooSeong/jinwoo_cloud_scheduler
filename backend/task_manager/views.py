"""View handlers for TaskManager"""
import logging
import json
from django.http import JsonResponse
from django.views import View
from django.db.utils import IntegrityError
from django.db.models import ProtectedError
from django.core.paginator import Paginator
from kubernetes.client import CoreV1Api
from kubernetes.client.rest import ApiException
from api.common import RESPONSE, get_uuid
from user_model.models import UserType
from config import KUBERNETES_NAMESPACE
from .models import TaskSettings, Task, TASK
from .executor import TaskExecutor, get_kubernetes_api_client

LOGGER = logging.getLogger(__name__)


class TaskSettingsListHandler(View):
    http_method_names = ['get', 'post']

    def get(self, request, **kwargs):
        """
        @api {get} /task_settings/ Get task settings list
        @apiName GetTaskSettingsList
        @apiGroup TaskSettings
        @apiVersion 0.1.0
        @apiPermission user

        @apiParam {Number} [order_by] Specifies list order criteria, available options:
        create_time, name. Use '-' sign to indicate reverse order.
        @apiParam {String} [page] Specifies the page number (starting from 1, per page 25 elements)
        @apiSuccess {Object} payload Response object
        @apiSuccess {Number} payload.page_count Page count
        @apiSuccess {Number} payload.count Total element count
        @apiSuccess {Object[]} payload.entry List of TaskSettings Object
        @apiSuccess {String} payload.entry.uuid Task uuid
        @apiSuccess {String} payload.entry.name Task name
        @apiSuccess {String} payload.entry.description Task description
        @apiSuccess {Object} [payload.entry.container_config] Detailed container config (admin only)
        @apiSuccess {Number} payload.entry.time_limit Task time limit
        @apiSuccess {Number} [payload.entry.replica] Replicas of containers (admin only)
        @apiSuccess {Number} [payload.entry.ttl_interval] Health check interval (admin only)
        @apiSuccess {Number} [payload.max_sharing_users] Max number of shared users (admin only)
        @apiSuccess {String} payload.entry.create_time Create time of task settings
        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse Unauthorized
        """
        response = RESPONSE.SUCCESS
        try:
            user = kwargs.get('__user', None)
            if user is None:
                raise Exception("Internal exception raised when trying to get `User` object.")
            params = request.GET
            payload = {}
            order_by = params.get('order_by', 'id').split(',')
            page = params.get('page', '1')
            page = int(page)
            all_pages = Paginator(TaskSettings.objects.filter().order_by(*order_by), 25)
            curr_page = all_pages.page(page)
            payload['count'] = all_pages.count
            payload['page_count'] = all_pages.num_pages if all_pages.count > 0 else 0
            payload['entry'] = []
            for item in curr_page.object_list:
                entry = {'uuid': item.uuid, 'name': item.name,
                         'description': item.description, 'create_time': item.create_time,
                         'time_limit': item.time_limit}
                if user.user_type == UserType.ADMIN or user.user_type == UserType.SUPER_ADMIN:
                    entry['container_config'] = json.loads(item.container_config)
                    entry['replica'] = item.replica
                    entry['ttl_interval'] = item.ttl_interval
                    entry['max_sharing_users'] = item.max_sharing_users
                payload['entry'].append(entry)
            response['payload'] = payload
        except ValueError:
            response = RESPONSE.INVALID_REQUEST
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)

    def post(self, request, **kwargs):
        """
        @api {post} /task_settings/ Create task settings
        @apiName CreateTaskSettings
        @apiGroup TaskSettings
        @apiVersion 0.1.0
        @apiPermission admin
        @apiParamExample {json} Request-Example:
        {
            "name": "task_name",
            "description": "This is a demo test.",
            "container_config": {
                    "image": "nginx:latest",
                    "persistent_volume": {
                            "name": "ceph-pvc",
                            "mount_path": "/var/image/"
                    },
                    "shell": "/bin/bash",
                    "commands": ["echo hello world", "echo $CLOUD_SCHEDULER_USER"],
                    "memory_limit": "128M",
                    "working_path": "/home/task/",
                    "task_script_path": "scripts/",
                    "task_initial_file_path": "initial/"
            },
            "time_limit": 900,
            "replica": 2,
            "ttl_interval": 5,
            "max_sharing_users": 1
        }
        @apiParam {String} name Task name
        @apiParam {String} description Task description
        @apiParam {Object} container_config Detailed container config
        @apiParam {Number} time_limit Task time limit
        @apiParam {Number} replica Replicas of containers
        @apiParam {Number} ttl_interval Health check interval
        @apiParam {Number} max_sharing_users Max number of shared users
        @apiSuccess {Object} payload Success payload is empty
        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse OperationFailed
        @apiUse Unauthorized
        @apiUse PermissionDenied
        """
        response = None
        try:
            user = kwargs.get('__user', None)
            executor = TaskExecutor.instance(new=False)
            if executor is None or not executor.ready:
                raise Exception("Task executor is not initialized, please wait...")
            if user is None:
                raise Exception("Internal exception raised when trying to get `User` object.")
            elif user.user_type == UserType.USER:
                response = RESPONSE.PERMISSION_DENIED
            else:
                query = json.loads(request.body)
                invalid = 'name' not in query.keys() or 'description' not in query.keys() or \
                          'container_config' not in query.keys() or 'time_limit' not in query.keys() or \
                          'replica' not in query.keys() or 'ttl_interval' not in query.keys() or \
                          'max_sharing_users' not in query.keys() or \
                          not isinstance(query['container_config'], dict) or \
                          not isinstance(query['time_limit'], int) or \
                          not isinstance(query['replica'], int) or not isinstance(query['ttl_interval'], int) or \
                          not isinstance(query['max_sharing_users'], int)
                if invalid:
                    response = RESPONSE.INVALID_REQUEST
                else:
                    item = TaskSettings.objects.create(uuid=str(get_uuid()), name=query['name'],
                                                       description=query['description'],
                                                       container_config=json.dumps(query['container_config']),
                                                       time_limit=query['time_limit'], replica=query['replica'],
                                                       ttl_interval=max(query['ttl_interval'], 1),
                                                       max_sharing_users=query['max_sharing_users'])
                    response = RESPONSE.SUCCESS
                    executor.schedule_task_settings(item)
        except ValueError:
            response = RESPONSE.INVALID_REQUEST
        except IntegrityError as ex:
            LOGGER.warning(ex)
            response = RESPONSE.OPERATION_FAILED
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)


class TaskSettingsItemHandler(View):
    http_method_names = ['get', 'put', 'delete']  # specify allowed methods

    def get(self, _, **kwargs):
        """
        @api {get} /task_settings/<string:uuid>/ Get detailed task settings
        @apiName GetTaskSettings
        @apiGroup TaskSettings
        @apiVersion 0.1.0
        @apiPermission admin

        @apiSuccess {Object} payload Response object
        @apiSuccess {String} payload.uuid Task uuid
        @apiSuccess {String} payload.name Task name
        @apiSuccess {String} payload.description Task description
        @apiSuccess {Object} payload.container_config Detailed container configs
        @apiSuccess {Number} payload.time_limit Task time limit
        @apiSuccess {Number} payload.replica Replicas of containers
        @apiSuccess {Number} payload.ttl_interval Health check interval
        @apiSuccess {Number} payload.max_sharing_users Max number of shared users
        @apiSuccess {String} payload.create_time Create time of task setting
        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse OperationFailed
        @apiUse Unauthorized
        @apiUse PermissionDenied
        """
        response = None
        try:
            uuid = kwargs.get('uuid', None)
            assert uuid is not None
            response = RESPONSE.SUCCESS
            item = TaskSettings.objects.get(uuid=uuid)
            response['payload'] = {'uuid': item.uuid, 'name': item.name, 'description': item.description,
                                   'container_config': json.loads(item.container_config), 'time_limit': item.time_limit,
                                   'replica': item.replica, 'ttl_interval': item.ttl_interval,
                                   'max_sharing_users': item.max_sharing_users, 'create_time': item.create_time}
        except TaskSettings.DoesNotExist:
            response = RESPONSE.OPERATION_FAILED
            response['message'] += " {}".format("Object does not exist.")
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)

    def put(self, request, **kwargs):
        """
        @api {put} /task_settings/<string:uuid>/ Update task settings
        @apiName UpdateTaskSettings
        @apiGroup TaskSettings
        @apiVersion 0.1.0
        @apiPermission admin
        @apiDescription Leave optional params empty to keep them as the original value
        @apiParamExample {json} Request-Example:
        {
            "name": "33"
        }
        @apiParam {String} [name] Task name
        @apiParam {String} [description] Task description
        @apiParam {Object} [container_config] Detailed container config
        @apiParam {Number} [time_limit] Task time limit
        @apiParam {Number} [replica] Replicas of containers
        @apiParam {Number} [ttl_interval] Health check interval
        @apiParam {Number} [max_sharing_users] Max number of shared users
        @apiSuccess {Object} payload Success payload is empty
        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse OperationFailed
        @apiUse Unauthorized
        @apiUse PermissionDenied
        """
        response = None
        try:
            uuid = kwargs.get('uuid', None)
            assert uuid is not None
            executor = TaskExecutor.instance(new=False)
            if executor is None or not executor.ready:
                raise Exception("Task executor is not initialized, please wait...")
            need_reschedule = False
            query = json.loads(request.body)
            response = RESPONSE.SUCCESS
            item = TaskSettings.objects.get(uuid=uuid)
            if 'name' in query.keys():
                item.name = str(query['name'])
            if 'description' in query.keys():
                item.description = str(query['description'])
            if 'container_config' in query.keys():
                item.container_config = json.dumps(dict(query['container_config']))
            if 'time_limit' in query.keys():
                item.time_limit = int(query['time_limit'])
            if 'replica' in query.keys():
                item.replica = int(query['replica'])
            if 'ttl_interval' in query.keys():
                item.ttl_interval = max(1, int(query['ttl_interval']))
                need_reschedule = True
            if 'max_sharing_users' in query.keys():
                item.max_sharing_users = int(query['max_sharing_users'])
            item.save(force_update=True)
            if need_reschedule:
                executor.schedule_task_settings(item)
        except ValueError:
            response = RESPONSE.INVALID_REQUEST
        except IntegrityError:
            response = RESPONSE.OPERATION_FAILED
            response['message'] += " {}".format("Name duplicates.")
        except TaskSettings.DoesNotExist:
            response = RESPONSE.OPERATION_FAILED
            response['message'] += " {}".format("Object does not exist.")
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)

    def delete(self, _, **kwargs):
        """
        @api {delete} /task_settings/<string:uuid>/ Delete task settings
        @apiName DeleteTaskSettings
        @apiGroup TaskSettings
        @apiVersion 0.1.0
        @apiPermission admin
        @apiSuccess {Object} payload Success payload is empty
        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse OperationFailed
        @apiUse Unauthorized
        @apiUse PermissionDenied
        """
        response = None
        try:
            uuid = kwargs.get('uuid', None)
            assert uuid is not None
            TaskSettings.objects.get(uuid=uuid).delete()
            response = RESPONSE.SUCCESS
        except TaskSettings.DoesNotExist:
            response = RESPONSE.OPERATION_FAILED
        except ProtectedError:
            response = RESPONSE.OPERATION_FAILED
            response['message'] += " Cannot delete task settings associated with tasks."
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)


class ConcreteTaskListHandler(View):
    http_method_names = ['get', 'post']

    def get(self, request, **kwargs):
        """
        @api {get} /task/ Get task list
        @apiName GetTaskSettingsList
        @apiDescription For user, the API returns tasks belong to him. For admin, the API returns all tasks.
        @apiGroup Task
        @apiVersion 0.1.0
        @apiPermission user

        @apiParam {Number} [page] Specifies the page number (starting from 1, per page 25 elements)
        @apiSuccess {Object} payload Response object
        @apiSuccess {Number} payload.page_count Page count
        @apiSuccess {Number} payload.count Total element count
        @apiSuccess {Object[]} payload.entry List of TaskSettings Object
        @apiSuccess {String} payload.entry.uuid Task uuid
        @apiSuccess {Number} payload.entry.status Task status code, defined as [SCHEDULED = 0, RUNNING = 1,
        SUCCEEDED = 2, FAILED = 3, DELETING = 4, PENDING = 5, TLE = 6, WAITING = 7, MLE = 8]
        @apiSuccess {String} payload.entry.user Name of the user that the task belongs to
        @apiSuccess {Object} payload.entry.settings Corresponding task setting
        @apiSuccess {String} payload.entry.settings.name Name of the task setting
        @apiSuccess {String} payload.entry.settings.uuid UUID of the task setting
        @apiSuccess {String} payload.entry.create_time Create time
        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse Unauthorized
        """
        response = RESPONSE.SUCCESS
        try:
            user = kwargs.get('__user', None)
            if user is None:
                raise Exception("Internal exception raised when trying to get `User` object.")
            page = request.GET.get('page', '1')
            page = int(page)
            filter_dict = {}
            if user.user_type == UserType.USER:
                filter_dict['user'] = user
            all_pages = Paginator(Task.objects.filter(**filter_dict).order_by("-create_time", "status"), 25)
            curr_page = all_pages.page(page)
            payload = {'count': all_pages.count, 'page_count': all_pages.num_pages if all_pages.count > 0 else 0,
                       'entry': []}
            for item in curr_page.object_list:
                payload['entry'].append({'settings': {'name': item.settings.name, 'uuid': item.settings.uuid},
                                         'status': item.status,
                                         'uuid': item.uuid,
                                         'user': item.user.username,
                                         'create_time': item.create_time})
            response['payload'] = payload
        except ValueError:
            response = RESPONSE.INVALID_REQUEST
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)

    def post(self, request, **kwargs):
        """
        @api {post} /task/ Create a task
        @apiName CreateTask
        @apiDescription Create a task corresponding to the given TaskSetting. The task will be automatically run.
        @apiGroup Task
        @apiVersion 0.1.0
        @apiPermission user

        @apiParam {String} settings_uuid UUID of TaskSetting
        @apiSuccess {Object} payload Response object
        @apiSuccess {String} payload.uuid Task uuid
        @apiSuccess {Number} payload.status Task status code, defined as [SCHEDULED = 0, RUNNING = 1,
        SUCCEEDED = 2, FAILED = 3, DELETING = 4, PENDING = 5, TLE = 6, WAITING = 7]
        @apiSuccess {String} payload.user Name of the user that the task belongs to
        @apiSuccess {Object} payload.settings Corresponding task setting
        @apiSuccess {String} payload.settings.name Name of the task setting
        @apiSuccess {String} payload.settings.uuid UUID of the task setting
        @apiSuccess {String} payload.create_time Create time
        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse Unauthorized
        """
        response = None
        try:
            user = kwargs.get('__user', None)
            if user is None:
                raise Exception("Internal exception raised when trying to get `User` object.")
            else:
                query = json.loads(request.body)
                if 'settings_uuid' not in query.keys():
                    response = RESPONSE.INVALID_REQUEST
                else:
                    settings = TaskSettings.objects.get(uuid=query['settings_uuid'])
                    item = Task.objects.create(user=user, settings=settings, uuid=str(get_uuid()))
                    response = RESPONSE.SUCCESS
                    response['payload'] = {'settings': {'name': item.settings.name, 'uuid': item.settings.uuid},
                                           'status': item.status,
                                           'uuid': item.uuid,
                                           'user': item.user.username,
                                           'create_time': item.create_time}
        except TaskSettings.DoesNotExist:
            response = RESPONSE.OPERATION_FAILED
            response["message"] += " Failed to find corresponding task settings."
        except ValueError:
            response = RESPONSE.INVALID_REQUEST
        except IntegrityError as ex:
            LOGGER.warning(ex)
            response = RESPONSE.OPERATION_FAILED
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)


class ConcreteTaskHandler(View):
    http_method_names = ['get', 'delete']

    @staticmethod
    def _get_task(arg_dict):
        user = arg_dict.get('__user', None)
        if user is None:
            raise Exception("Internal exception raised when trying to get `User` object.")
        uuid = arg_dict.get('uuid', None)
        if uuid is None:
            return None
        else:
            if user.user_type == UserType.ADMIN or user.user_type == UserType.SUPER_ADMIN:
                item = Task.objects.get(uuid=uuid)
            else:
                item = Task.objects.get(uuid=uuid, user=user)
            return item

    def get(self, _, **kwargs):
        """
        @api {get} /task/<uuid>/ Get detailed task info
        @apiName GetTaskInfoDetail
        @apiGroup Task
        @apiVersion 0.1.0
        @apiPermission user

        @apiParam {String} uuid UUID of the task
        @apiSuccess {Object} payload Response object
        @apiSuccess {String} payload.uuid Task uuid
        @apiSuccess {Number} payload.status Task status code, defined as [SCHEDULED = 0, RUNNING = 1,
        SUCCEEDED = 2, FAILED = 3, DELETING = 4, PENDING = 5, TLE = 6, WAITING = 7]
        @apiSuccess {String} payload.user Name of the user that the task belongs to
        @apiSuccess {Object} payload.settings Corresponding task setting
        @apiSuccess {String} payload.settings.name Name of the task setting
        @apiSuccess {String} payload.settings.uuid UUID of the task setting
        @apiSuccess {Number} payload.exit_code Exit code of the task
        @apiSuccess {String} payload.log Logs of the task
        @apiSuccess {String} payload.create_time Create time
        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse OperationFailed
        @apiUse Unauthorized
        """
        response = RESPONSE.SUCCESS
        api = CoreV1Api(get_kubernetes_api_client())
        try:
            item = self._get_task(kwargs)
            if item is None:
                response = RESPONSE.INVALID_REQUEST
            else:
                # logs are not crunched to WebServer when pods are running, so query from k8s directly in this case
                log = item.logs
                if item.status == TASK.RUNNING:
                    try:
                        resp = api.list_namespaced_pod(namespace=KUBERNETES_NAMESPACE,
                                                       label_selector="app={}".format(item.uuid))
                        if resp.items:
                            log = api.read_namespaced_pod_log(name=resp.items[0].metadata.name,
                                                              namespace=KUBERNETES_NAMESPACE)
                    except ApiException:
                        log = 'Failed to get logs from running pod.'
                response['payload'] = {'settings': {'name': item.settings.name, 'uuid': item.settings.uuid},
                                       'status': item.status,
                                       'uuid': item.uuid,
                                       'user': item.user.username,
                                       'log': log,
                                       'exit_code': item.exit_code,
                                       'create_time': item.create_time}
        except Task.DoesNotExist:
            response = RESPONSE.OPERATION_FAILED
            response['message'] += " Object does not exist."
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)

    def delete(self, _, **kwargs):
        """
        @api {delete} /task/<uuid>/ Delete task
        @apiName DeleteTask
        @apiGroup Task
        @apiVersion 0.1.0
        @apiPermission user

        @apiParam {String} uuid UUID of the task

        @apiUse APIHeader
        @apiUse Success
        @apiUse ServerError
        @apiUse InvalidRequest
        @apiUse OperationFailed
        @apiUse Unauthorized
        """
        response = RESPONSE.SUCCESS
        try:
            item = self._get_task(kwargs)
            if item is None:
                response = RESPONSE.INVALID_REQUEST
            else:
                item.status = TASK.DELETING  # schedule canceling by changing status
                item.save(force_update=True)
        except Task.DoesNotExist:
            response = RESPONSE.OPERATION_FAILED
            response['message'] += " Object does not exist."
        except Exception as ex:
            LOGGER.error(ex)
            response = RESPONSE.SERVER_ERROR
        finally:
            return JsonResponse(response)
