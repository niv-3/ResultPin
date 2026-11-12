from pathlib import Path

from django.core.management import BaseCommand, call_command
from django.db import transaction

from store.models import ServiceCategory


class Command(BaseCommand):
    help = "Initialize the beta catalogue from a private Render secret file."

    def handle(self, *args, **options):
        call_command("check_vtpass_connection")
        fixture = Path("/etc/secrets/kobotap-beta-catalogue.json")
        if not fixture.is_file():
            return

        with transaction.atomic():
            if ServiceCategory.objects.exists():
                self.stdout.write("Catalogue already initialized.")
                return
            call_command("loaddata", str(fixture))
