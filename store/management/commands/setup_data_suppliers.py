from django.core.management import BaseCommand

from store.models import DataSupplier, Vendor


class Command(BaseCommand):
    help = "Create disabled data supplier profiles. Does not activate or fund suppliers."

    def handle(self, *args, **options):
        for adapter, name in (("cheapdata", "CheapData"), ("nellobyte", "Nellobyte"),
                              ("bilalsada", "Bilalsadasub")):
            if DataSupplier.objects.filter(adapter=adapter).exists():
                continue
            vendor = Vendor.objects.filter(name__iexact=name).first()
            if vendor is None:
                vendor = Vendor.objects.create(name=name, is_active=False)
            DataSupplier.objects.create(vendor=vendor, adapter=adapter)
        self.stdout.write("Supplier profiles ready. All new profiles remain disabled; no credentials stored.")
