from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_alter_rating_fetched_at"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE TRIGGER catalog_rating_no_update "
                "BEFORE UPDATE ON catalog_rating "
                "FOR EACH ROW BEGIN "
                "SELECT RAISE(ABORT, 'rating snapshots are append-only'); "
                "END;"
            ),
            reverse_sql="DROP TRIGGER IF EXISTS catalog_rating_no_update;",
        ),
    ]