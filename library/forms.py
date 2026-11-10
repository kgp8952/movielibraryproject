from django import forms

from library.models import Collection, UserSettings


class UserSettingsForm(forms.ModelForm):
    class Meta:
        model = UserSettings
        fields = ["preferred_country", "interface_language"]


class CollectionForm(forms.ModelForm):
    class Meta:
        model = Collection
        fields = ["name", "description"]