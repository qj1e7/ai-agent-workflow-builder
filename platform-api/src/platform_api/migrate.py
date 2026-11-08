import os
import sys
from collections.abc import Mapping

from platform_api.auth import ConfigError
from platform_api.bootstrap import migrate_to_head
from platform_api.settings import owner_database_url_from_env


def main(env: Mapping[str, str] | None = None) -> int:
    def say(message: str) -> None:
        print(f"migrate: {message}", flush=True)

    try:
        owner_url = owner_database_url_from_env(os.environ if env is None else env)
    except ConfigError as error:
        say(str(error))
        return 1
    return 0 if migrate_to_head(owner_url, say) else 1


if __name__ == "__main__":
    sys.exit(main())
