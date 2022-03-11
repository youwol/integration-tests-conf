import asyncio
import os
import shutil
from pathlib import Path
import brotli
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from youwol.configuration.config_from_module import IConfigurationFactory, Configuration
from youwol.environment.clients import RemoteClients
from youwol.environment.youwol_environment import YouwolEnvironment
from youwol.middlewares.models_dispatch import AbstractDispatch
from youwol.routers.custom_commands.models import Command
from youwol.utils.utils_low_level import execute_shell_cmd, sed_inplace
from youwol_utils.context import Context
from youwol.main_args import MainArguments
from youwol_utils.request_info_factory import url_match
from youwol_utils.utils_paths import parse_json


async def clone_project(git_url: str, new_project_name: str, ctx: Context):

    folder_name = new_project_name.split("/")[-1]
    env = await ctx.get('env', YouwolEnvironment)
    parent_folder = env.pathsBook.config.parent / 'projects'
    dst_folder = parent_folder / folder_name
    await execute_shell_cmd(cmd=f"(cd {parent_folder} && git clone {git_url})",
                            context=ctx)
    os.rename(parent_folder / git_url.split('/')[-1].split('.')[0], parent_folder / folder_name)
    old_project_name = parse_json(dst_folder / 'package.json')['name']
    sed_inplace(dst_folder / 'package.json', old_project_name, new_project_name)
    sed_inplace(dst_folder / 'index.html', old_project_name, new_project_name)
    return {}


async def purge_downloads(ctx: Context):

    assets_gtw = await RemoteClients.get_assets_gateway_client(ctx)
    env: YouwolEnvironment = await ctx.get('env', YouwolEnvironment)
    default_drive = await env.get_default_drive(context=ctx)
    resp = await assets_gtw.get_tree_folder_children(default_drive.downloadFolderId)
    await asyncio.gather(
        *[assets_gtw.delete_tree_item(item["treeId"]) for item in resp["items"]],
        *[assets_gtw.delete_tree_folder(item["folderId"]) for item in resp["folders"]]
    )
    await assets_gtw.purge_drive(default_drive.driveId)
    return {}


async def reset(ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
    env.reset_cache()
    parent_folder = env.pathsBook.config.parent
    shutil.rmtree(parent_folder / "databases", ignore_errors=True)
    shutil.rmtree(parent_folder / "projects", ignore_errors=True)
    shutil.rmtree(parent_folder / "youwol_system", ignore_errors=True)
    os.mkdir(parent_folder / "projects")
    shutil.copytree(src=parent_folder / "empty_databases",
                    dst=parent_folder / "databases")


async def create_remote_folder(body, ctx):
    assets_gtw = await RemoteClients.get_assets_gateway_client(ctx)
    await assets_gtw.create_folder(parent_folder_id=body['parentFolderId'], body=body)


class BrotliDecompress(AbstractDispatch):

    async def apply(self, incoming_request: Request, call_next: RequestResponseEndpoint, context: Context):

        if url_match(incoming_request, "GET:/api/assets-gateway/raw/package/**"):
            response = await call_next(incoming_request)
            if response.headers.get('content-encoding') != 'br':
                return response

            binary = b''
            async for data in response.body_iterator:
                binary += data
            headers = {k: v for k, v in response.headers.items()
                       if k not in ['content-length', 'content-encoding']}
            return Response(brotli.decompress(binary).decode('utf8'), headers=headers)

        return None

    def __str__(self):
        return "Decompress brotli on te fly because in jest brotli is not supported"


class ConfigurationFactory(IConfigurationFactory):

    async def get(self, main_args: MainArguments) -> Configuration:
        return Configuration(
            httpPort=2001,
            dataDir=Path(__file__).parent / 'databases',
            cacheDir=Path(__file__).parent / 'youwol_system',
            projectsDirs=[Path(__file__).parent / 'projects'],
            dispatches=[
                BrotliDecompress()
            ],
            customCommands=[
                Command(
                    name="reset",
                    do_get=lambda ctx: reset(ctx)
                ),
                Command(
                    name="clone-project",
                    do_post=lambda body, ctx: clone_project(body['url'], body['name'], ctx)
                ),
                Command(
                    name="purge-downloads",
                    do_delete=lambda ctx: purge_downloads(ctx)
                ),
                Command(
                    name="create-remote-folder",
                    do_post=lambda body, ctx: create_remote_folder(body, ctx)
                ),
                Command(
                    name="test-cmd-post",
                    do_post=lambda body, ctx: body["returnObject"]
                ),
                Command(
                    name="test-cmd-put",
                    do_put=lambda body, ctx: body["returnObject"]
                ),
                Command(
                    name="test-cmd-delete",
                    do_delete=lambda ctx: {"status": "deleted"}
                )
            ]
        ).extending_profile(
            name='profile-1',
            conf=Configuration()
        )
