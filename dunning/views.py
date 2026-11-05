from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.rechte import nur_inhaber
from accounts.typen import FirmaRequest
from audit.services import protokolliere

from .forms import MahnplanForm
from .services import basiszinsen, mahnplan_fuer


@nur_inhaber
def mahnplan(request: FirmaRequest) -> HttpResponse:
    plan = mahnplan_fuer(request.firma)
    form = MahnplanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        geaendert = {f: str(form.cleaned_data[f]) for f in form.changed_data if not f.startswith(("text_", "betreff_"))}
        texte = [f for f in form.changed_data if f.startswith(("text_", "betreff_"))]
        plan = form.save(commit=False)
        plan.geaendert = timezone.now()
        plan.save()
        protokolliere(
            request.firma,
            "mahnplan.geaendert",
            nutzer=request.user,
            objekt=plan,
            daten={"werte": geaendert, "texte": texte},
        )
        messages.success(request, "Mahnplan gespeichert.")
        return redirect("dunning:mahnplan")
    return render(request, "dunning/mahnplan.html", {"form": form, "basiszinsen": basiszinsen()})
