import requests


GITHUB_API = (
    "https://api.github.com/repos/"
    "bildobodo/lcnc-suite"
)

GITHUB_REPOSITORY = (
    "https://github.com/bildobodo/lcnc-suite"
)

GITHUB_BRANCH = "main"


class WebGUIResolver:

    def latest_commit(self) -> dict:

        url = (
            f"{GITHUB_API}/commits/{GITHUB_BRANCH}"
        )

        response = requests.get(
            url,
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        return {
            "branch": GITHUB_BRANCH,
            "commit": data["sha"],
            "message": data["commit"]["message"],
            "date": data["commit"]["author"]["date"],
            "url": data["html_url"],
        }

    def resolve(
        self,
        linuxcnc_version: str,
        architecture: str,
        realtime: bool,
    ) -> dict:

        """
        Resolves WebGUI (LCNC Suite) information from GitHub.
        
        Returns latest commit info and performs basic compatibility checks:
        - Architecture must be arm64
        - Realtime kernel is required
        
        Without a formal verification matrix, status is 'compatible' if
        basic requirements are met, 'incompatible' if not.
        """

        commit = self.latest_commit()

        result = {
            "provider": "lcnc-suite",
            "version": commit["commit"][:8],
            "repository": GITHUB_REPOSITORY,
            "branch": commit["branch"],
            "commit": commit["commit"],
            "commit_message": commit["message"],
            "commit_date": commit["date"],
            "commit_url": commit["url"],
            "status": "compatible",
            "reason": None,
        }

        # Basic compatibility checks
        if architecture != "arm64":

            result["status"] = "incompatible"
            result["reason"] = (
                "LCNC Suite requires ARM64 architecture."
            )

            return result

        if not realtime:

            result["status"] = "incompatible"
            result["reason"] = (
                "LCNC Suite requires a realtime kernel."
            )

            return result

        # If basic checks pass, mark as compatible
        # (Full verification matrix can be added later)
        result["reason"] = (
            f"LCNC Suite {result['version']} "
            "is compatible with this configuration."
        )

        return result