import os
import shutil
from pathlib import Path

import brotli
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from youwol.environment import Projects, Command, Configuration, YouwolEnvironment, \
    System, CloudEnvironments, LocalEnvironment, Customization, \
    CustomMiddleware, CustomEndPoints, DirectAuth, CloudEnvironment, get_standard_auth_provider, Connection

from youwol_utils.context import Context, Label


async def reset(ctx: Context):
    env = await ctx.get('env', YouwolEnvironment)
    env.reset_cache()
    env.reset_databases()
    parent_folder = env.pathsBook.config.parent
    shutil.rmtree(parent_folder / "projects", ignore_errors=True)
    shutil.rmtree(parent_folder / "youwol_system", ignore_errors=True)
    os.mkdir(parent_folder / "projects")


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


users = [
    (os.getenv("USERNAME_INTEGRATION_TESTS"), os.getenv("PASSWORD_INTEGRATION_TESTS")),
    (os.getenv("USERNAME_INTEGRATION_TESTS_BIS"), os.getenv("PASSWORD_INTEGRATION_TESTS_BIS"))
]
direct_auths = [DirectAuth(authId=email, userName=email, password=pwd)
                for email, pwd in users]

prod_env = CloudEnvironment(
    envId="prod",
    host="platform.youwol.com",
    authProvider=get_standard_auth_provider("platform.youwol.com"),
    authentications=direct_auths
)

Configuration(
    system=System(
        httpPort=2001,
        cloudEnvironments=CloudEnvironments(
            defaultConnection=Connection(envId='prod', authId=direct_auths[0].authId),
            environments=[prod_env]
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
