from django import forms

from library.models import Collection, UserSettings


PROVIDER_CHOICES = (
    ("tmdb", "TMDB"),
    ("omdb", "OMDb"),
    ("kinopoisk", "Kinopoisk"),
    ("disc", "Disc catalogue"),
)


class UserSettingsForm(forms.ModelForm):
    enabled_providers = forms.MultipleChoiceField(
        choices=PROVIDER_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Enabled providers",
    )

    class Meta:
        model = UserSettings
        fields = ["preferred_country", "interface_language"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["enabled_providers"] = [
                name for name, enabled in (self.instance.enabled_providers or {}).items() if enabled
            ]

    def save(self, commit=True):
        instance = super().save(commit=False)
        selected = set(self.cleaned_data.get("enabled_providers", []))
        instance.enabled_providers = {name: name in selected for name, _ in PROVIDER_CHOICES}
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class CollectionForm(forms.ModelForm):
    class Meta:
        model = Collection
        fields = ["name", "description"]