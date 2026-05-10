from django.utils.translation import gettext_lazy as _

from core.forms.base import BootstrapModelForm
from core.models import SystemSettings


class SystemSettingsForm(BootstrapModelForm):
    class Meta:
        model = SystemSettings
        fields = ["use_locations"]
        help_texts = {
            "use_locations": _(
                "Якщо вимкнено, у наступному етапі складські операції будуть "
                "працювати без вибору локацій."
            ),
        }
