from django.core.management import BaseCommand

from store.data_routing import select_data_quote, total_supplier_cost
from store.models import ServicePlan


class Command(BaseCommand):
    help = "Preview the best approved data routes without charging wallets or purchasing anything."

    def handle(self, *args, **options):
        plans = ServicePlan.objects.filter(is_active=True, provider__is_active=True,
            provider__category__is_active=True, provider__category__slug__in=("data", "internet-data"))
        for plan in plans.select_related("provider"):
            quote = select_data_quote(plan)
            if quote:
                self.stdout.write(f"{plan.code}: {quote.vendor.name}, cost incl. reserve {total_supplier_cost(quote)}; retail {plan.selling_price}")
            else:
                self.stdout.write(f"{plan.code}: no eligible route")
