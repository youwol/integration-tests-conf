import os
import shutil
from pathlib import Path

import brotli
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from youwol.configuration.models_config import Projects, RemoteConfig, DirectAuthUser
from youwol.environment.config_from_module import IConfigurationFactory, Configuration
from youwol.environment.youwol_environment import YouwolEnvironment
from youwol.main_args import MainArguments
from youwol.middlewares.models_dispatch import AbstractDispatch
from youwol.routers.custom_commands.models import Command
from youwol_utils.clients.oidc.oidc_config import PublicClient
from youwol_utils.context import Context
from youwol_utils.request_info_factory import url_match


async def reset(ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
    env.reset_cache()
    parent_folder = env.pathsBook.config.parent
    shutil.rmtree(parent_folder / "projects", ignore_errors=True)
    shutil.rmtree(parent_folder / "databases", ignore_errors=True)
    shutil.rmtree(parent_folder / "youwol_system", ignore_errors=True)
    os.mkdir(parent_folder / "projects")
    shutil.copytree(src=parent_folder / "empty_databases",
                    dst=parent_folder / "databases")


class BrotliDecompress(AbstractDispatch):

    async def apply(self, incoming_request: Request, call_next: RequestResponseEndpoint, context: Context):

        async with context.start(action="Apply BrotliDecompress") as ctx:  # type: Context
            match_cdn, params = url_match(incoming_request, "GET:/api/assets-gateway/raw/package/*/**")
            await ctx.info(text="parameters", data={"matchCdn": match_cdn, "params": params})

            match_files, _ = url_match(incoming_request, "GET:/api/assets-gateway/files-backend/files/*")
            if match_cdn or match_files:
                response = await call_next(incoming_request)
                await ctx.info(text="apply brotli decompression on response")
                if response.headers.get('content-encoding') != 'br':
                    return response

                await context.info("Apply brotli decompression")
                binary = b''
                # noinspection PyUnresolvedReferences
                async for data in response.body_iterator:
                    binary += data
                headers = {k: v for k, v in response.headers.items()
                           if k not in ['content-length', 'content-encoding']}
                decompressed = brotli.decompress(binary)
                resp = Response(decompressed.decode('utf8'), headers=headers)
                return resp

            return None


class ConfigurationFactory(IConfigurationFactory):

    async def get(self, main_args: MainArguments) -> Configuration:
        username = os.getenv("USERNAME_INTEGRATION_TESTS")
        password = os.getenv("PASSWORD_INTEGRATION_TESTS")
        username_bis = os.getenv("USERNAME_INTEGRATION_TESTS_BIS")
        password_bis = os.getenv("PASSWORD_INTEGRATION_TESTS_BIS")
        return Configuration(
            httpPort=2001,
            remotes=[
                RemoteConfig.build(
                    default_user=username,
                    direct_auth_users=[
                        DirectAuthUser(username=username, password=password),
                        DirectAuthUser(username=username_bis, password=password_bis)
                        ],
                    openid_client=PublicClient(
                        client_id="tbd_test_openid_connect_js"
                    ),
                    host="platform.youwol.com"
                )
            ],
            dataDir=Path(__file__).parent / 'databases',
            cacheDir=Path(__file__).parent / 'youwol_system',
            projects=Projects(
                finder=Path(__file__).parent / 'projects'
            ),
            dispatches=[
                BrotliDecompress()
            ],
            customCommands=[
                Command(
                    name="reset",
                    do_get=lambda ctx: reset(ctx)
                )
            ]
        )
