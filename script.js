const municipalities = ["الجلفة","عين وسارة","القرنيني","البيرين","بنهار","سيدي لعجال","الخميس","حاسي فدول","حد الصحاري","بويرة الأحداب","عين أفقه","حاسي بحبح","الزعفران","حاسي العش","عين معبد","دار الشيوخ","مليليحة","سيدي بايزيد","الشارف","القديد","بن يعقوب","الإدريسية","الدويس","عين الشهداء","عين الإبل","مجبارة","تعضميت","زكار","مسعد","دلدول","سلمانة","سد رحال","قطارة","فيض البطمة","عمورة","أم العظام"];

let csrfToken = "";
let currentUser = null;
let authMode = "login";

async function readResponse(response) {
  const body = await response.text();
  let data;
  try { data = JSON.parse(body); }
  catch {
    throw new Error(response.status >= 500
      ? `حدث خطأ في الخادم (${response.status}). أعد المحاولة لاحقًا.`
      : `استجابة الخادم غير متوقعة (${response.status}). حدّث الصفحة وحاول مجددًا.`);
  }
  if (!response.ok) throw new Error(data.error || "تعذر تنفيذ الطلب.");
  return data;
}

function normalizeAlgerianPhone(value) {
  const digits = value.replace(/[^0-9]/g, "");
  if (digits.startsWith("213")) return `0${digits.slice(3)}`;
  return digits;
}

function formatAlgerianPhone(value) {
  const digits = normalizeAlgerianPhone(value);
  if (!/^0\d{9}$/.test(digits)) return value.trim();
  return `${digits.slice(0, 4)} ${digits.slice(4, 6)} ${digits.slice(6, 8)} ${digits.slice(8)}`;
}

function setAuthStatus(message, type = "") {
  const status = document.querySelector("#auth-status");
  status.textContent = message;
  status.className = `form-status auth-status ${type}`.trim();
}

function setFieldError(input, message = "") {
  input.classList.toggle("invalid", Boolean(message));
  input.setAttribute("aria-invalid", String(Boolean(message)));
  let hint = input.parentElement.querySelector(".field-error");
  if (message && !hint) {
    hint = document.createElement("span");
    hint.className = "field-error";
    hint.style.cssText = "color:#b94b4b;font-size:11px;font-weight:500";
    input.parentElement.append(hint);
  }
  if (hint) hint.textContent = message;
}

function validateAuthForm(form, mode) {
  let valid = true;
  const name = form.elements.name;
  const phone = form.elements.phone;
  const password = form.elements.password;

  if (name) {
    const message = name.value.trim().length < 2 ? "أدخل اسمًا صحيحًا مكوّنًا من حرفين على الأقل." : "";
    setFieldError(name, message); valid = !message && valid;
  }

  const digits = normalizeAlgerianPhone(phone.value);
  const phoneMessage = /^0(5|6|7)\d{8}$/.test(digits) ? "" : "أدخل رقمًا جزائريًا صحيحًا يبدأ بـ 05 أو 06 أو 07.";
  setFieldError(phone, phoneMessage); valid = !phoneMessage && valid;

  const passwordMessage = password.value.length < 8
    ? "كلمة المرور يجب أن تتكون من 8 أحرف على الأقل."
    : password.value.length > 128 ? "كلمة المرور طويلة جدًا." : "";
  setFieldError(password, passwordMessage); valid = !passwordMessage && valid;
  return valid;
}

function setAuthMode(mode) {
  authMode = mode;
  document.querySelectorAll(".auth-tab").forEach((tab) => {
    const active = tab.dataset.authView === mode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelector("#login-form").hidden = mode !== "login";
  document.querySelector("#register-form").hidden = mode !== "register";
  document.querySelector("#auth-title").textContent = mode === "login" ? "مرحبًا بعودتك" : "أنشئ حسابك";
  document.querySelector(".auth-intro").textContent = mode === "login"
    ? "سجّل الدخول لمتابعة إعلاناتك والتعليق على العقارات."
    : "أنشئ حسابًا مجانيًا لتتمكن من التعليق ومتابعة إعلاناتك.";
  setAuthStatus("");
  const activeForm = document.querySelector(mode === "login" ? "#login-form" : "#register-form");
  activeForm.querySelector("input")?.focus();
}

function openLogin(mode = "login") {
  setAuthMode(mode);
  document.querySelector("#auth-modal").showModal();
}

async function loadAuthState() {
  try {
    const data = await readResponse(await fetch("/api/auth/me"));
    csrfToken = data.csrf_token;
    currentUser = data.user;
  } catch (error) {
    console.error("Could not load the account session.", error);
  }
}

async function apiAuthRequest(url, payload) {
  if (!csrfToken) await loadAuthState();
  return readResponse(await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    credentials: "same-origin",
    body: JSON.stringify(payload)
  }));
}

function updateAccountButton() {
  const button = document.querySelector("#account-button");
  if (!button) return;
  button.textContent = currentUser ? "تسجيل الخروج" : "تسجيل الدخول";
  button.title = currentUser ? `الحساب: ${currentUser.name}` : "تسجيل الدخول أو إنشاء حساب";
}

async function submitAuthForm(form, mode) {
  if (!validateAuthForm(form, mode)) {
    setAuthStatus("راجع الحقول المحددة ثم أعد المحاولة.", "error");
    return;
  }

  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  submit.classList.add("loading");
  submit.querySelector("span").textContent = mode === "login" ? "جارٍ تسجيل الدخول…" : "جارٍ إنشاء الحساب…";
  setAuthStatus("");

  const payload = Object.fromEntries(new FormData(form));
  payload.phone = normalizeAlgerianPhone(payload.phone);

  try {
    const endpoint = mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const data = await apiAuthRequest(endpoint, payload);
    currentUser = data.user;
    csrfToken = data.csrf_token;
    updateAccountButton();
    form.reset();
    setAuthStatus(mode === "login" ? "تم تسجيل الدخول بنجاح." : "تم إنشاء حسابك بنجاح.", "success");
    window.setTimeout(() => document.querySelector("#auth-modal").close(), 350);
  } catch (error) {
    setAuthStatus(error.message || "تعذر إتمام العملية. حاول مرة أخرى.", "error");
  } finally {
    submit.disabled = false;
    submit.classList.remove("loading");
    submit.querySelector("span").textContent = mode === "login" ? "دخول آمن" : "إنشاء الحساب";
  }
}

document.querySelectorAll(".auth-tab").forEach((tab) => {
  tab.addEventListener("click", () => setAuthMode(tab.dataset.authView));
});

document.querySelectorAll(".password-toggle").forEach((toggle) => {
  toggle.addEventListener("click", () => {
    const input = toggle.parentElement.querySelector("input");
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    toggle.textContent = reveal ? "إخفاء" : "إظهار";
    toggle.setAttribute("aria-label", reveal ? "إخفاء كلمة المرور" : "إظهار كلمة المرور");
    toggle.setAttribute("aria-pressed", String(reveal));
  });
});

document.querySelectorAll(".auth-phone").forEach((input) => {
  input.addEventListener("blur", () => {
    if (input.value.trim()) input.value = formatAlgerianPhone(input.value);
  });
  input.addEventListener("input", () => setFieldError(input));
});

document.querySelectorAll(".auth-form input").forEach((input) => {
  input.addEventListener("input", () => setFieldError(input));
});

document.querySelector("#login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuthForm(event.currentTarget, "login");
});

document.querySelector("#register-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuthForm(event.currentTarget, "register");
});

const accountButton = document.querySelector("#account-button");
if (accountButton) {
  accountButton.addEventListener("click", async () => {
    if (!currentUser) { openLogin("login"); return; }
    accountButton.disabled = true;
    try {
      const data = await apiAuthRequest("/api/auth/logout", {});
      csrfToken = data.csrf_token;
      currentUser = null;
      updateAccountButton();
      setAuthStatus("تم تسجيل الخروج بنجاح.", "success");
    } catch (error) {
      setAuthStatus(error.message, "error");
      openLogin("login");
    } finally {
      accountButton.disabled = false;
    }
  });
}

const authModal = document.querySelector("#auth-modal");
if (authModal) {
  authModal.addEventListener("click", (event) => {
    if (event.target === authModal) authModal.close();
  });
  authModal.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      setAuthMode(authMode === "login" ? "register" : "login");
    }
  });
}

loadAuthState().finally(updateAccountButton);
