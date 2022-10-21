import django_tables2 as tables

from .models import Building


class BuildingTable(tables.Table):
    class Meta:
        model = Building
        template_name = "tables/table.html"
        # template_name = "django_tables2/bootstrap.html"
        fields = ("id", "id_source", "height", "age", "type")
