"""
This example script imports the getaltsclient package and
prints out the version.
"""

import getaltsclient


def main():
    print(
        f"getaltsclient version: {getaltsclient.__version__}"
    )


if __name__ == "__main__":
    main()
