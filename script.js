const municipalities = ["الجلفة","عين وسارة","القرنيني","البيرين","بنهار","سيدي لعجال","الخميس","حاسي فدول","حد الصحاري","بويرة الأحداب","عين أفقه","حاسي بحبح","الزعفران","حاسي العش","عين معبد","دار الشيوخ","مليليحة","سيدي بايزيد","الشارف","القديد","بن يعقوب","الإدريسية","الدويس","عين الشهداء","عين الإبل","مجبارة","تعضميت","زكار","مسعد","دلدول","سلمانة","سد رحال","قطارة","فيض البطمة","عمورة","أم العظام"];
const grid = document.querySelector("#property-grid");
const statusMessage = document.querySelector("#properties-status");
const favoriteStorageKey = "dark-favorites";
const favorites = loadFavorites();
let properties = [];
let currentFilters = {};
let purpose = "sale";
let showAll = false;
let showFavorites = false;
let sortMode = "newest";
let csrfToken = "";
let currentUser = null;
let activeListingId = null;
let authMode = "login";

function loadFavorites() {
  try {
    const stored = JSON.parse(localStorage.getItem(favoriteStorageKey) || "[]");
    if (!Array.isArray(stored)) throw new TypeError("Saved favorites must be an array.");
    return new Set(stored.filter((id) => Number.isSafeInteger(id) && id > 0));
  } catch (error) {
    console.error("Could not load saved favorites.", error);
    return new Set();
  }
}

function saveFavorites() {
  try {
    localStorage.setItem(favoriteStorageKey, JSON.stringify([...favorites]));
  } catch (error) {
    statusMessage.textContent = "تعذر حفظ المفضلة على هذا الجهاز.";
    console.error("Could not save favorites.", error);
  }
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

async function readResponse(response) {
  const body = await response.text();
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    if (response.status === 405) {
      const endpoint = response.url ? new URL(response.url).pathname : "الخدمة المطلوبة";
      const allowedMethods = response.headers.get("Allow");
      throw new Error(
        `طريقة الطلب غير مسموحة للمسار ${endpoint} (405). أعد تشغيل الموقع وحدّث الصفحة.${
          allowedMethods ? ` الطرق المقبولة: ${allowedMethods}.` : ""
        }`
      );
    }
    const message = response.status >= 500
      ? `حدث خطأ في الخادم (${response.status}). أعد المحاولة لاحقًا.`
      : `استجابة الخادم غير متوقعة (${response.status}). حدّث الصفحة وحاول مجددًا.`;
    throw new Error(message);
  }
  if (!response.ok) throw new Error(data.error || "تعذر تنفيذ الطلب.");
  return data;
}

function formatPrice(property) {
  const amount = new Intl.NumberFormat("ar-DZ").format(property.price);
  return property.purpose === "rent" ? `${amount} دج / شهريًا` : `${amount} دج`;
}

function sortedProperties(items) {
  return [...items].sort((first, second) => {
    if (sortMode === "price-asc") return first.price - second.price;
    if (sortMode === "price-desc") return second.price - first.price;
    if (sortMode === "area-desc") return (second.area || 0) - (first.area || 0);
    return Date.parse(second.created_at) - Date.parse(first.created_at);
  });
}

function propertyCard(property) {
  const card = makeElement("article", "property-card");
  card.dataset.id = property.id;
  const imageWrap = makeElement("div", "property-image");
  const image = makeElement("img");
  image.src = property.image || "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=900&q=82";
  image.alt = property.title;
  image.loading = "lazy";
  image.addEventListener("error", () => {
    if (image.dataset.fallback) return;
    image.dataset.fallback = "true";
    image.src = "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=900&q=82";
  });
  imageWrap.append(image);
  imageWrap.append(makeElement("span", "property-badge", property.is_demo ? "مثال توضيحي" : property.purpose === "sale" ? "للبيع" : "للإيجار"));

  const favorite = makeElement("button", `favorite-button ${favorites.has(property.id) ? "active" : ""}`);
  favorite.type = "button";
  favorite.setAttribute("aria-label", favorites.has(property.id) ? "إزالة من المفضلة" : "إضافة للمفضلة");
  favorite.dataset.favorite = property.id;
  favorite.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z"/></svg>';
  imageWrap.append(favorite);

  const body = makeElement("div", "property-body");
  body.append(makeElement("p", "property-price", formatPrice(property)));
  body.append(makeElement("h3", "property-title", property.title));
  body.append(makeElement("p", "property-location", `${property.location}، ولاية الجلفة`));
  const meta = makeElement("div", "property-meta");
  if (property.rooms) meta.append(makeElement("span", "", `${property.rooms} غرف`));
  if (property.area) meta.append(makeElement("span", "", `${property.area} م²`));
  meta.append(makeElement("span", "", property.type));
  body.append(meta);
  card.append(imageWrap, body);
  return card;
}

function renderProperties(items = properties) {
  grid.replaceChildren();
  const matching = showFavorites ? items.filter((property) => favorites.has(property.id)) : items;
  const sorted = sortedProperties(matching);
  document.querySelector("#results-count").textContent = `${matching.length} عقار`;
  const visible = showAll ? sorted : sorted.slice(0, 6);
  if (!visible.length) {
    grid.append(makeElement("p", "empty-state", showFavorites ? "لم تضف عقارات إلى المفضلة بعد." : "لا توجد عقارات مطابقة لبحثك حاليًا."));
    return;
  }
  visible.forEach((property) => grid.append(propertyCard(property)));
}

async function loadProperties(filters = {}) {
  statusMessage.textContent = "جارٍ تحميل العقارات…";
  const query = new URLSearchParams(filters);
  try {
    const data = await readResponse(await fetch(`/api/listings?${query}`));
    properties = data.items;
    currentFilters = filters;
    statusMessage.textContent = properties.some((property) => property.is_demo)
      ? "العقارات الموسومة «مثال توضيحي» بيانات تجريبية وليست عروضًا حقيقية."
      : "";
    renderProperties();
  } catch (error) {
    properties = [];
    renderProperties();
    statusMessage.textContent = error.message || "تعذر الاتصال بالخادم. تحقق من اتصالك ثم أعد تحميل الصفحة.";
  }
}

function updateAccountButton() {
  const button = document.querySelector("#account-button");
  button.textContent = currentUser ? "تسجيل الخروج" : "تسجيل الدخول";
  button.title = currentUser ? `الحساب: ${currentUser.name}` : "تسجيل الدخول أو إنشاء حساب";
}

async function loadAuthState() {
  try {
    const data = await readResponse(await fetch("/api/auth/me"));
    csrfToken = data.csrf_token;
    currentUser = data.user;
    updateAccountButton();
  } catch (error) {
    console.error("Could not load the account session.", error);
  }
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
  document.querySelector("#auth-status").textContent = "";
}

function openLogin() {
  setAuthMode("login");
  document.querySelector("#auth-modal").showModal();
}

async function apiAuthRequest(url, payload) {
  if (!csrfToken) await loadAuthState();
  return readResponse(await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(payload)
  }));
}

document.querySelector("#municipality-list").innerHTML = municipalities.map((name) =>
  `<button type="button" data-location="${name}">${name}</button>`
).join("");
document.querySelector("#listing-location").insertAdjacentHTML(
  "beforeend",
  municipalities.map((name) => `<option value="${name}">${name}</option>`).join("")
);

document.querySelectorAll(".search-tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".search-tab").forEach((item) => item.classList.remove("active"));
  tab.classList.add("active");
  purpose = tab.dataset.purpose;
}));

document.querySelector("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  showAll = true;
  showFavorites = false;
  const filters = { purpose };
  const type = document.querySelector("#property-type").value;
  const location = document.querySelector("#location-filter").value;
  const maxPrice = document.querySelector("#price-filter").value;
  const minRooms = document.querySelector("#rooms-filter").value;
  if (type) filters.type = type;
  if (location) filters.location = location.replace(/^دائرة\s+/, "");
  if (maxPrice) filters.max_price = maxPrice;
  if (minRooms) filters.min_rooms = minRooms;
  loadProperties(filters);
  document.querySelector("#properties").scrollIntoView({ behavior: "smooth" });
});

document.querySelector("#view-all").addEventListener("click", () => {
  showAll = true;
  showFavorites = false;
  loadProperties(currentFilters);
});

document.querySelector("#sort-select").addEventListener("change", (event) => {
  sortMode = event.currentTarget.value;
  renderProperties();
});

document.querySelector("#favorites-button").addEventListener("click", () => {
  showFavorites = !showFavorites;
  showAll = true;
  renderProperties();
  document.querySelector("#properties").scrollIntoView({ behavior: "smooth" });
});

grid.addEventListener("click", (event) => {
  const favorite = event.target.closest("[data-favorite]");
  if (favorite) {
    event.stopPropagation();
    const id = Number(favorite.dataset.favorite);
    favorites.has(id) ? favorites.delete(id) : favorites.add(id);
    saveFavorites();
    document.querySelector("#favorite-count").textContent = favorites.size;
    renderProperties();
    return;
  }
  const card = event.target.closest(".property-card");
  if (card) openDetail(Number(card.dataset.id));
});

function renderGallery(property, container) {
  const images = property.images?.length ? property.images : property.image ? [property.image] : [];
  if (!images.length) {
    const placeholder = makeElement("div", "detail-image-placeholder", "لا توجد صور مرفقة");
    container.append(placeholder);
    return;
  }
  const mainImage = makeElement("img", "detail-main-image");
  mainImage.src = images[0];
  mainImage.alt = property.title;
  container.append(mainImage);
  if (images.length > 1) {
    const thumbnails = makeElement("div", "detail-thumbnails");
    images.forEach((src, index) => {
      const thumbnail = makeElement("button", `detail-thumbnail ${index === 0 ? "active" : ""}`);
      thumbnail.type = "button";
      thumbnail.setAttribute("aria-label", `عرض الصورة ${index + 1}`);
      const preview = makeElement("img");
      preview.src = src;
      preview.alt = "";
      thumbnail.append(preview);
      thumbnail.addEventListener("click", () => {
        mainImage.src = src;
        thumbnails.querySelectorAll(".detail-thumbnail").forEach((item) => item.classList.remove("active"));
        thumbnail.classList.add("active");
      });
      thumbnails.append(thumbnail);
    });
    container.append(thumbnails);
  }
}

function renderComments(comments) {
  const list = document.querySelector("#comments-list");
  list.replaceChildren();
  document.querySelector("#comment-count").textContent = `${comments.length} تعليق`;
  if (!comments.length) {
    list.append(makeElement("p", "empty-comments", "لا توجد تعليقات بعد. كن أول من يشارك رأيه."));
    return;
  }
  comments.forEach((comment) => {
    const card = makeElement("article", "comment-card");
    const header = makeElement("header");
    header.append(makeElement("span", "", comment.name));
    const time = makeElement("time", "", new Date(comment.created_at).toLocaleDateString("ar-DZ"));
    header.append(time);
    card.append(header, makeElement("p", "", comment.body));
    list.append(card);
  });
}

async function loadComments(listing) {
  const form = document.querySelector("#comment-form");
  const status = document.querySelector("#comment-status");
  const list = document.querySelector("#comments-list");
  document.querySelector("#comment-count").textContent = "—";
  list.replaceChildren(makeElement("p", "empty-comments", "جارٍ تحميل التعليقات…"));
  form.hidden = Boolean(listing.is_demo);
  status.textContent = listing.is_demo ? "ستتوفر التعليقات على الإعلانات الحقيقية بعد نشرها." : "";
  if (listing.is_demo) {
    renderComments([]);
    return;
  }
  try {
    const data = await readResponse(await fetch(`/api/listings/${listing.id}/comments`));
    renderComments(data.items);
  } catch (error) {
    list.replaceChildren();
    status.textContent = error.message;
  }
}

function openDetail(id) {
  const property = properties.find((item) => item.id === id);
  if (!property) return;
  activeListingId = property.id;
  const content = document.querySelector("#detail-content");
  content.replaceChildren();
  const layout = makeElement("div", "detail-layout");
  const gallery = makeElement("div", "detail-gallery");
  renderGallery(property, gallery);
  const info = makeElement("div", "detail-info");
  info.append(makeElement("span", "property-badge", property.is_demo ? "مثال توضيحي" : property.purpose === "sale" ? "للبيع" : "للإيجار"));
  info.append(makeElement("h2", "", property.title));
  info.append(makeElement("p", "property-price", formatPrice(property)));
  info.append(makeElement("p", "detail-location", `${property.location}، ولاية الجلفة`));
  const details = [
    property.rooms ? `عدد الغرف: ${property.rooms}` : "",
    property.area ? `المساحة: ${property.area} م²` : "",
    `نوع العقار: ${property.type}`,
    property.description || ""
  ].filter(Boolean).join(" · ");
  info.append(makeElement("p", "detail-description", details));
  const actions = makeElement("div", "detail-actions");
  if (property.is_demo || !property.phone) {
    actions.append(makeElement("p", "", "بيانات التواصل غير متاحة للإعلانات التوضيحية."));
  } else {
    const phone = property.phone.replace(/[^\d+]/g, "");
    const call = makeElement("a", "", "اتصال بالمالك");
    call.href = `tel:${phone}`;
    const whatsapp = makeElement("a", "", "واتساب");
    whatsapp.href = `https://wa.me/${phone.replace(/\D/g, "")}`;
    whatsapp.target = "_blank";
    whatsapp.rel = "noopener";
    actions.append(call, whatsapp);
  }
  info.append(actions);
  layout.append(gallery, info);
  content.append(layout);
  document.querySelector("#comment-body").value = "";
  document.querySelector("#comment-status").textContent = "";
  loadComments(property);
  document.querySelector("#detail-modal").showModal();
}

document.querySelector(".detail-close").addEventListener("click", () => document.querySelector("#detail-modal").close());

document.querySelectorAll("[data-location]").forEach((button) => button.addEventListener("click", () => {
  const location = button.dataset.location;
  const select = document.querySelector("#location-filter");
  const matchingOption = [...select.options].find((option) => option.value === location);
  if (matchingOption) select.value = matchingOption.value;
  else select.value = "";
  document.querySelector("#search-form").requestSubmit();
}));

document.querySelectorAll("[data-open-listing]").forEach((button) => button.addEventListener("click", () => {
  document.querySelector("#listing-status").textContent = "";
  document.querySelector("#listing-modal").showModal();
}));

document.querySelector("#listing-images").addEventListener("change", (event) => {
  const input = event.currentTarget;
  const files = [...input.files];
  const status = document.querySelector("#listing-status");
  const validTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
  const invalid = files.length > 8 || files.some((file) => file.size > 4 * 1024 * 1024 || !validTypes.has(file.type));
  if (invalid) {
    input.value = "";
    document.querySelector("#image-preview").replaceChildren();
    status.textContent = "اختر حتى 8 صور بصيغة JPG أو PNG أو WEBP، وبحجم لا يتجاوز 4 ميغابايت للصورة.";
    return;
  }
  status.textContent = "";
  const preview = document.querySelector("#image-preview");
  preview.replaceChildren();
  files.forEach((file) => {
    const image = makeElement("img");
    image.src = URL.createObjectURL(file);
    image.alt = file.name;
    image.addEventListener("load", () => URL.revokeObjectURL(image.src), { once: true });
    preview.append(image);
  });
});

document.querySelector("#listing-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const status = document.querySelector("#listing-status");
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  status.textContent = "";
  try {
    const response = await fetch("/api/listings", { method: "POST", body: new FormData(form) });
    const data = await readResponse(response);
    status.textContent = "استلمنا إعلانك وصور العقار. سيظهر بعد مراجعته.";
    form.reset();
    document.querySelector("#image-preview").replaceChildren();
  } catch (error) {
    status.textContent = error.message || "تعذر الإرسال. يرجى المحاولة مجددًا.";
  } finally {
    submit.disabled = false;
  }
});

document.querySelectorAll(".auth-tab").forEach((tab) => tab.addEventListener("click", () => {
  setAuthMode(tab.dataset.authView);
}));

document.querySelector("#account-button").addEventListener("click", async () => {
  if (!currentUser) {
    openLogin();
    return;
  }
  const button = document.querySelector("#account-button");
  button.disabled = true;
  try {
    const data = await apiAuthRequest("/api/auth/logout", {});
    csrfToken = data.csrf_token;
    currentUser = null;
    updateAccountButton();
  } catch (error) {
    document.querySelector("#auth-status").textContent = error.message;
    document.querySelector("#auth-modal").showModal();
  } finally {
    button.disabled = false;
  }
});

async function submitAuthForm(form, mode) {
  const status = document.querySelector("#auth-status");
  const submit = form.querySelector('[type="submit"]');
  const payload = Object.fromEntries(new FormData(form));
  submit.disabled = true;
  status.textContent = "";
  try {
    const endpoint = mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const data = await apiAuthRequest(endpoint, payload);
    currentUser = data.user;
    csrfToken = data.csrf_token;
    updateAccountButton();
    form.reset();
    document.querySelector("#auth-modal").close();
    document.querySelector("#comment-status").textContent = "";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

document.querySelector("#login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuthForm(event.currentTarget, "login");
});
document.querySelector("#register-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuthForm(event.currentTarget, "register");
});

document.querySelector("#comment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!activeListingId) return;
  if (!currentUser) {
    openLogin();
    document.querySelector("#comment-status").textContent = "سجّل الدخول أولًا لإضافة تعليق.";
    return;
  }
  const form = event.currentTarget;
  const submit = form.querySelector('[type="submit"]');
  const status = document.querySelector("#comment-status");
  submit.disabled = true;
  status.textContent = "";
  try {
    await apiAuthRequest(`/api/listings/${activeListingId}/comments`, {
      body: document.querySelector("#comment-body").value
    });
    form.reset();
    status.textContent = "تم استلام تعليقك، وسيظهر بعد مراجعته.";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

document.querySelector("#menu-button").addEventListener("click", (event) => {
  const nav = document.querySelector("#main-nav");
  const open = nav.classList.toggle("open");
  event.currentTarget.setAttribute("aria-expanded", String(open));
});
document.querySelectorAll("#main-nav a").forEach((link) => link.addEventListener("click", () => {
  document.querySelector("#main-nav").classList.remove("open");
  document.querySelector("#menu-button").setAttribute("aria-expanded", "false");
}));

document.querySelector("#favorite-count").textContent = favorites.size;
loadProperties();
loadAuthState();
