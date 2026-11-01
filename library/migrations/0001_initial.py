import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Collection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='CollectionItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField(default=0)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('collection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='library.collection')),
                ('movie', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='catalog.movie')),
            ],
            options={
                'ordering': ['position', 'added_at'],
            },
        ),
        migrations.AddField(
            model_name='collection',
            name='movies',
            field=models.ManyToManyField(related_name='collections', through='library.CollectionItem', to='catalog.movie'),
        ),
        migrations.CreateModel(
            name='LibraryEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('watchlist', 'Watchlist'), ('watched', 'Watched')], default='watchlist', max_length=16)),
                ('is_favorite', models.BooleanField(default=False)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('watched_at', models.DateField(blank=True, null=True)),
                ('personal_rating', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('movie', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='library_entries', to='catalog.movie')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-added_at'],
            },
        ),
        migrations.CreateModel(
            name='OwnedDisc',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('edition_notes', models.CharField(blank=True, max_length=255)),
                ('purchased_at', models.DateField(blank=True, null=True)),
                ('movie', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='owned_copies', to='catalog.movie')),
                ('release', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_copies', to='catalog.discrelease')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['movie__title_original'],
            },
        ),
        migrations.AddConstraint(
            model_name='collectionitem',
            constraint=models.UniqueConstraint(fields=('collection', 'movie'), name='unique_collection_movie'),
        ),
        migrations.AddConstraint(
            model_name='collection',
            constraint=models.UniqueConstraint(fields=('user', 'name'), name='unique_user_collection_name'),
        ),
        migrations.AddConstraint(
            model_name='libraryentry',
            constraint=models.UniqueConstraint(fields=('user', 'movie'), name='unique_user_library_movie'),
        ),
        migrations.AddConstraint(
            model_name='libraryentry',
            constraint=models.CheckConstraint(condition=models.Q(('personal_rating__isnull', True), models.Q(('personal_rating__gte', 1), ('personal_rating__lte', 10)), _connector='OR'), name='personal_rating_1_to_10'),
        ),
        migrations.AddConstraint(
            model_name='owneddisc',
            constraint=models.UniqueConstraint(fields=('user', 'movie', 'release', 'edition_notes'), name='unique_owned_disc_copy'),
        ),
    ]
