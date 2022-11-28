import os
import shutil
from pathlib import Path

import brotli
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from youwol.environment import Projects, IConfigurationFactory, Configuration, YouwolEnvironment, Impersonation, \
    System, CloudEnvironments, ImpersonateAuthConnection, get_standard_youwol_cloud, LocalEnvironment, Customization, \
    CustomMiddleware, CustomEndPoints
from youwol.main_args import MainArguments
from youwol.routers.custom_commands.models import Command
from youwol_utils.context import Context, Label


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


class BrotliDecompressMiddleware(CustomMiddleware):

    """
        Simple middleware that logs incoming and outgoing headers
        """
    async def dispatch(
            self,
            incoming_request: Request,
            call_next: RequestResponseEndpoint,
            context: Context
    ):

        async with context.start(
                action="BrotliDecompressMiddleware.dispatch",
                with_labels=[Label.MIDDLEWARE]
        ) as ctx:  # type: Context

            response = await call_next(incoming_request)
            if response.headers.get('content-encoding') != 'br':
                return response
            await ctx.info(text="Got 'br' content-encoding => apply brotli decompresson")
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


class ConfigurationFactory(IConfigurationFactory):

    async def get(self, main_args: MainArguments) -> Configuration:
        host = "platform.youwol.com"
        users = [
            (os.getenv("USERNAME_INTEGRATION_TESTS"), os.getenv("PASSWORD_INTEGRATION_TESTS")),
            (os.getenv("USERNAME_INTEGRATION_TESTS_BIS"), os.getenv("PASSWORD_INTEGRATION_TESTS_BIS"))
        ]
        impersonations = [Impersonation(userId=email, userName=email, password=pwd, forHosts=[host])
                          for email, pwd in users]
        return Configuration(
            system=System(
                httpPort=2001,
                cloudEnvironments=CloudEnvironments(
                    defaultConnection=ImpersonateAuthConnection(host=host, userId=users[0][0]),
                    environments=[
                        get_standard_youwol_cloud(host=host),
                    ],
                    impersonations=impersonations
                ),
                localEnvironment=LocalEnvironment(
                    dataDir=Path(__file__).parent / 'databases',
                    cacheDir=Path(__file__).parent / 'youwol_system',)
            ),
            projects=Projects(
                finder=Path(__file__).parent / 'projects'
            ),
            customization=Customization(
                middlewares=[
                    BrotliDecompressMiddleware()
                ],
                endPoints=CustomEndPoints(
                    commands=[Command(
                        name="reset",
                        do_get=lambda ctx: reset(ctx)
                    )]
                )
            )
        )
