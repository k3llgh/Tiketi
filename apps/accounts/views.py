"""accounts/views.py"""
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django_htmx.http import HttpResponseClientRedirect


def login_view(request):
    if request.user.is_authenticated:
        return redirect("events:index")
    if request.method == "POST":
        method = request.POST.get("method", "email")
        if method == "email":
            user = authenticate(
                request,
                email=request.POST.get("email","").strip(),
                password=request.POST.get("password",""),
            )
            if user:
                login(request, user)
                return HttpResponseClientRedirect(request.GET.get("next","/")) if request.htmx else redirect(request.GET.get("next","events:index"))
            error = "Invalid email or password."
            return render(request,"accounts/partials/login_error.html",{"error":error}) if request.htmx else render(request,"accounts/login.html",{"error":error})
        elif method == "phone_request":
            phone = request.POST.get("phone","").strip()
            from apps.accounts.models import User
            try:
                user = User.objects.get(phone=phone)
                from apps.accounts.services import generate_and_send_otp
                generate_and_send_otp(user)
                request.session["otp_phone"] = phone
                return render(request,"accounts/partials/otp_form.html") if request.htmx else render(request,"accounts/login.html",{"show_otp":True,"phone":phone})
            except User.DoesNotExist:
                error = "No account with that number."
                return render(request,"accounts/partials/login_error.html",{"error":error}) if request.htmx else render(request,"accounts/login.html",{"error":error})
        elif method == "phone_verify":
            phone = request.session.get("otp_phone","")
            user  = authenticate(request, phone=phone, otp_code=request.POST.get("otp_code","").strip())
            if user:
                login(request, user)
                request.session.pop("otp_phone",None)
                return HttpResponseClientRedirect("/") if request.htmx else redirect("events:index")
            error = "Invalid or expired code."
            return render(request,"accounts/partials/login_error.html",{"error":error}) if request.htmx else render(request,"accounts/login.html",{"show_otp":True,"error":error})
    return render(request,"accounts/login.html")


def register_fan_view(request):
    if request.user.is_authenticated:
        return redirect("events:index")
    if request.method == "POST":
        from apps.accounts.services import create_fan
        try:
            user = create_fan(
                email=request.POST.get("email"),
                phone=request.POST.get("phone"),
                password=request.POST.get("password"),
                first_name=request.POST.get("first_name",""),
                last_name=request.POST.get("last_name",""),
            )
            login(request, user, backend="apps.accounts.backends.EmailBackend")
            return redirect("events:index")
        except Exception as exc:
            messages.error(request, str(exc))
    return render(request,"accounts/register_fan.html")


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


def register_vendor_view(request):
    if request.method == "POST":
        from apps.accounts.services import create_vendor
        try:
            user = create_vendor(
                email=request.POST["email"],
                password=request.POST["password"],
                vendor_name=request.POST["vendor_name"],
                phone=request.POST["phone"],
                tier=request.POST["tier"],
            )
            login(request, user, backend="apps.accounts.backends.EmailBackend")
            return redirect("accounts:stake")
        except Exception as exc:
            messages.error(request, str(exc))
    return render(request,"accounts/register_vendor.html")


@login_required
def stake_view(request):
    user = request.user
    if not user.is_vendor:
        return redirect("events:index")
    if user.vendor_status == user.VendorStatus.ACTIVE:
        return redirect("accounts:vendor_dashboard")
    from django.conf import settings
    cfg = settings.TIKETI
    amount = cfg["STAKE_SMALL_CENTS"] if user.vendor_tier=="small" else cfg["STAKE_BIG_CENTS"]
    return render(request,"accounts/stake.html",{"tier":user.vendor_tier,"amount_cents":amount,"amount_usd":amount/100})


@login_required
def vendor_dashboard_view(request):
    if not request.user.is_vendor:
        return redirect("events:index")
    from apps.events.models import Event
    events = Event.objects.filter(vendor=request.user).order_by("-kickoff")[:20]
    return render(request,"accounts/vendor_dashboard.html",{"events":events,"vendor":request.user})


@login_required
def fan_dashboard_view(request):
    from apps.tickets.models import Ticket
    tickets = Ticket.objects.filter(
        user=request.user,status__in=["active","pending_payment","resold"]
    ).select_related("event").order_by("-purchased_at")
    return render(request,"accounts/fan_dashboard.html",{"tickets":tickets})
