"""Store provider interface. Each store (Steam, GOG, Epic) implements this."""


class Provider:
    id = "base"
    name = "Base"
    login_fields = []   # [{"key","label","secret"}] for text-entry logins; empty = browser login

    def status(self):
        """{'linked': bool, 'account': str, 'ready': bool, 'note': str}"""
        raise NotImplementedError

    def library(self):
        """Every game the account owns: [{'id','title','art','installed','note'}]"""
        raise NotImplementedError

    def installed(self):
        return [g for g in self.library() if g.get("installed")]

    def login(self, job, fields):
        raise NotImplementedError

    def logout(self):
        raise NotImplementedError

    def install(self, job, game_id):
        raise NotImplementedError

    def uninstall(self, job, game_id):
        raise NotImplementedError

    def launch(self, game_id):
        raise NotImplementedError


def game(provider, gid, title, art=None, installed=False, note=""):
    return {"provider": provider, "id": str(gid), "title": title, "art": art,
            "installed": installed, "note": note}
