const $ = (id) => document.getElementById(id);
const esc = (s) =>
    String(s ?? "").replace(
        /[&<>"']/g,
        (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
const money = (n) => Number(n).toLocaleString("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " грн";
const number = (n) => (n === null ? "" : Number(n).toLocaleString("uk-UA", { maximumFractionDigits: 3 }));
const formatTime = (s) =>
    s ? new Date(s).toLocaleString("uk-UA", { timeZone: "Europe/Kyiv", dateStyle: "short", timeStyle: "short" }) : "";
let state = {
    recipes: [],
    shopping: [],
    prices: {},
    selected: {},
    multipliers: {},
    messages: [],
    source_text: "",
    run_id: "",
    session_id: null,
};
let generalMessages = [];
let editRow = null;
let candidateTarget = null;
let extracting = false;
let pricing = false;
let chatBusy = { recipe: false, general: false };
let lastError = "";
let suggestions = [];
async function api(path, data) {
    const options =
        data === undefined
            ? {}
            : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) };
    const response = await fetch("/api/" + path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Не вдалося виконати запит.");
    return result;
}
function notice(text, good = false) {
    $("notice").textContent = text;
    $("notice").className = "notice" + (good ? " good" : "");
    lastError = good ? "" : text;
    if (good)
        setTimeout(() => {
            if ($("notice").textContent === text) $("notice").classList.add("hidden");
        }, 6500);
}
function quantity(row) {
    let q =
        row.quantity_min === null
            ? "Кількість не вказана"
            : number(row.quantity_min) +
              (row.quantity_min !== row.quantity_max ? "–" + number(row.quantity_max) : "") +
              (row.unit ? " " + row.unit : "");
    if (row.unknown_quantity && row.quantity_min !== null) q += " + не вказано";
    return q;
}
function packAmount(s) {
    let match;
    let last = null;
    const re = /(\d+(?:[.,]\d+)?)\s*(кг|мл|шт\.?|г|л)(?![а-яіїєґa-z])/gi;
    while ((match = re.exec(s))) last = match;
    if (!last) return [null, null];
    let q = Number(last[1].replace(",", "."));
    let u = last[2].replace(".", "");
    if (u === "кг") {
        q *= 1000;
        u = "г";
    }
    if (u === "л") {
        q *= 1000;
        u = "мл";
    }
    return [q, u];
}
function estimate(row, p) {
    const original = row;
    let approximate = !!row.is_estimate;
    if (row.budget_estimate && (row.quantity_max === null || row.unknown_quantity || row.unit !== p.package_unit)) {
        row = { ...row, ...row.budget_estimate, unknown_quantity: false };
        approximate = true;
    }
    const pantry = /сіль|перець|лавр|паприк|трав|олія|кетчуп|соус|цукор/i.test(original.name);
    if (!p.weighted && pantry && (row.quantity_max === null || row.unknown_quantity || row.unit !== p.package_unit))
        return {
            purchase_cost: p.price,
            purchase_label: "1 уп. попередньо",
            note: "Одна упаковка для орієнтовної покупки. Можна виключити, якщо є вдома.",
            approximate: true,
        };
    if (row.quantity_max === null || row.unknown_quantity)
        return { purchase_cost: null, note: "Кількість не повністю задана." };
    if (!p.package_quantity || row.unit !== p.package_unit)
        return { purchase_cost: null, note: "Уточніть одиниці та фасування." };
    const fraction = row.quantity_max / p.package_quantity;
    const buy = p.weighted
        ? Math.ceil((fraction - 1e-10) / (p.step || 0.1)) * (p.step || 0.1)
        : Math.ceil(fraction - 1e-10);
    if (p.stock !== null && p.stock !== undefined && buy > Number(p.stock))
        return { purchase_cost: null, note: "Наявної кількості недостатньо." };
    return {
        purchase_cost: Math.round(buy * p.price * 100) / 100,
        approximate,
        purchase_label: number(buy) + (p.weighted ? " " + p.price_unit : " уп."),
        note:
            (approximate ? "Попередня оцінка кількості. " : "") +
            (row.quantity_min !== row.quantity_max ? "За верхньою межею діапазону." : ""),
    };
}
function selectedProduct(row, store) {
    const products = state.prices[row.id]?.[store]?.products || [];
    return products.find((p) => p.id === state.selected[row.id]?.[store]) || products[0] || null;
}
function priceCell(row, store) {
    const result = state.prices[row.id]?.[store];
    const p = selectedProduct(row, store);
    const label = store === "atb" ? "АТБ" : "Сільпо";
    if (!result)
        return `<div class="price-cell"><span class="price-label">${label}</span><div class="product-name">Поки без ціни</div></div>`;
    if (!p)
        return `<div class="price-cell"><span class="price-label">${label}</span><button data-candidates="${row.id}" data-store="${store}">${result.status === "out_of_stock" ? "Немає в наявності" : "Не знайдено"}</button><div class="product-name">${esc(result.message || "Нічого не знайдено")}</div></div>`;
    const e = estimate(row, p);
    const info =
        p.source === "manual" ? "Введено вручну" : result.stale ? "Старий кеш" : result.cache ? "Кеш" : "Із каталогу";
    return `<div class="price-cell"><span class="price-label">${label} · ${info}</span><button data-candidates="${row.id}" data-store="${store}">${money(p.price)} / ${esc(p.price_unit)}</button><div class="product-name"><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.name)}</a>${p.package_label ? " · " + esc(p.package_label) : ""}</div><div class="price-sub">${e.purchase_cost !== null ? `${esc(e.purchase_label)} ≈ ${money(e.purchase_cost)}` : esc(e.note)}${e.note && e.purchase_cost !== null ? " · " + esc(e.note) : ""}</div><div class="price-label">${formatTime(p.fetched_at)} · <button class="text-button" data-candidates="${row.id}" data-store="${store}">Змінити товар</button></div></div>`;
}

function rowStatus(row) {
    const notes = (row.notes || []).join(" ").toLowerCase();
    if (notes.includes("повтор")) return "<small>Повтор у рецепті — перевірте один раз</small>";
    if (row.budget_estimate)
        return (
            '<small class="budget-hint">Для кошторису ≈ ' +
            esc(quantity({ ...row, ...row.budget_estimate, unknown_quantity: false })) +
            "</small>"
        );
    if (row.unknown_quantity || row.quantity_max === null)
        return '<small class="neutral-hint">Кількість у рецепті не зазначена</small>';
    if (row.quantity_min !== row.quantity_max) return '<small class="neutral-hint">Діапазон із рецепта</small>';
    if (row.alternatives?.length)
        return '<small class="neutral-hint">Є альтернатива: ' + esc(row.alternatives.join(", ")) + "</small>";
    return "";
}

function renderShopping() {
    const active = state.shopping.filter((x) => !x.excluded);
    $("item-count").textContent = active.length;
    $("shopping-empty").classList.toggle("hidden", state.shopping.length > 0);
    $("shopping-content").classList.toggle("hidden", !state.shopping.length);
    $("save-session").disabled = !state.recipes.length;
    $("shopping-summary").textContent =
        `${active.length} продуктів · ${state.recipes.length} рецепт${state.recipes.length === 1 ? "" : "и"}`;
    const oldFilter = $("category-filter").value;
    const cats = [...new Set(state.shopping.map((r) => r.category || "Інше"))];
    $("category-filter").innerHTML =
        '<option value="">Усі відділи</option>' +
        cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    if (cats.includes(oldFilter)) $("category-filter").value = oldFilter;
    const filtered = state.shopping.filter(
        (r) => !$("category-filter").value || r.category === $("category-filter").value,
    );
    $("shopping-list").innerHTML = filtered
        .map(
            (row, index, rows) =>
                (index === 0 || rows[index - 1].category !== row.category
                    ? `<h3 class="category-heading">${esc(row.category || "Інше")}</h3>`
                    : "") +
                `<article class="shopping-row${row.excluded ? " excluded" : ""}"><div class="row-top"><div class="item-name">${esc(row.name)}${row.is_estimate ? '<small class="estimate-label">AI-оцінка · було: ' + esc(row.original_quantity || "не вказано") + "</small>" : ""}${rowStatus(row)}</div><button class="row-quantity" data-edit="${row.id}">${esc(quantity(row))}</button></div><label class="pantry"><input type="checkbox" data-pantry="${row.id}" ${row.excluded ? "checked" : ""}> Є вдома / не купувати</label><details class="sources"><summary>Звідки кількість · ${row.sources.length} згад.</summary><ul>${row.sources.map((s) => `<li><b>${esc(s.recipe)}:</b> ${esc(s.quote)}${s.excluded ? " (виключено)" : ""}</li>`).join("")}</ul>${row.notes.map((n) => `<p>${esc(n)}</p>`).join("")}${row.alternatives.length ? "<p>Альтернатива: " + esc(row.alternatives.join(", ")) + ". Виберіть один продукт через редагування.</p>" : ""}</details>${!row.excluded ? '<div class="row-prices">' + priceCell(row, "atb") + priceCell(row, "silpo") + "</div>" : ""}</article>`,
        )
        .join("");
    renderTotals();
}
function renderTotals() {
    if (!Object.keys(state.prices).length) {
        $("store-totals").innerHTML = "";
        $("price-notes").textContent = "";
        return;
    }
    const active = state.shopping.filter((r) => !r.excluded);
    $("store-totals").innerHTML = ["atb", "silpo"]
        .map((store) => {
            let total = 0;
            let found = 0;
            let calculated = 0;
            let stale = 0;
            let manual = 0;
            let approximated = 0;
            const missingNames = [];
            const unpricedNames = [];
            for (const row of active) {
                const p = selectedProduct(row, store);
                if (!p) {
                    missingNames.push(row.name);
                    continue;
                }
                found++;
                if (state.prices[row.id]?.[store]?.stale) stale++;
                if (p.source === "manual") manual++;
                const e = estimate(row, p);
                if (e.approximate) approximated++;
                if (e.purchase_cost !== null) {
                    total += e.purchase_cost;
                    calculated++;
                } else unpricedNames.push(row.name);
            }
            return `<div class="total-card"><span>${store === "atb" ? "АТБ" : "Сільпо"} · ${calculated === active.length ? "Орієнтовний кошик" : "Не всі товари пораховані"}</span><strong>${calculated ? money(total) : "Немає суми"}</strong><small>Пораховано ${calculated} із ${active.length} продуктів. Знайдено ${found}.${stale ? " Старий кеш: " + stale + "." : ""}${manual ? " Ручні ціни: " + manual + "." : ""}${approximated ? " Попередніх кількостей: " + approximated + "." : ""}</small>${missingNames.length ? '<small class="missing-summary">Не знайдено: ' + esc(missingNames.join(", ")) + ".</small>" : ""}${unpricedNames.length ? "<small>Без суми: " + esc(unpricedNames.join(", ")) + ".</small>" : ""}</div>`;
        })
        .join("");
    $("price-notes").textContent =
        "Це попередній кошик, а не точна вартість з’їдених інгредієнтів. Для штук використано позначені оцінки ваги; для невизначених спецій, соусів та олії — одну упаковку. Для діапазонів беремо верхню межу, для упаковок — цілу кількість. Вагові товари рахуються за кроком каталогу; фактична вага може відрізнятися. Доставка й знижки за карткою не включені. Неповні кошториси не визначають дешевший магазин. Обрані товари потрібно перевірити.";
}
function renderRecipes() {
    $("recipe-cards").innerHTML = state.recipes
        .map(
            (r) =>
                `<section class="recipe-result"><div class="section-title"><h3>${esc(r.title)}</h3><span class="badge">${r.ingredients.length} інгредієнтів</span></div><span class="recipe-meta">${r.servings ? number(r.servings) + " порцій у рецепті" : "Порції не вказані"}</span><label class="portion">Множник кількості <input type="number" min="0.1" max="20" step="0.1" value="${state.multipliers[r.id] || 1}" data-multiplier="${r.id}" aria-label="Множник для ${esc(r.title)}"></label><details class="ingredient-review"><summary class="muted">Інгредієнти та подача</summary>${r.ingredients.map((i) => `<label><input type="checkbox" data-ingredient="${i.id}" ${!i.excluded ? "checked" : ""}><span>${esc(i.name)} · ${esc(quantity(i))}${i.optional ? ' <span class="badge">Для подачі</span>' : ""}${i.notes ? "<small>" + esc(i.notes) + "</small>" : ""}</span></label>`).join("")}</details></section>`,
        )
        .join("");
    $("recipe-chat-card").classList.toggle("hidden", !state.recipes.length);
}
async function aggregate() {
    const data = await api("aggregate", { recipes: state.recipes, multipliers: state.multipliers });
    state.shopping = data.shopping.map((r) => ({
        ...r,
        ...(state.overrides?.[r.id] || {}),
        budget_estimate: state.budget_estimates?.[r.id],
    }));
    renderShopping();
}
function renderMessages(mode) {
    const msgs = mode === "recipe" ? state.messages : generalMessages;
    const box = $(mode === "recipe" ? "recipe-messages" : "general-messages");
    if (!msgs.length && mode === "general") {
        box.innerHTML =
            '<div class="chat-welcome"><span>✦</span><h3>Чим допомогти?</h3><p>Поставте запитання або обговорімо вашу ідею.</p></div>';
        return;
    }
    box.innerHTML =
        msgs
            .map(
                (m) =>
                    `<div class="message ${m.role}"><small>${m.role === "user" ? "Ви" : "Смак & Кошик"}</small>${esc(m.content)}</div>`,
            )
            .join("") +
        (chatBusy[mode] ? '<div class="message assistant"><span class="spinner"></span> Готуємо відповідь…</div>' : "");
    box.scrollTop = box.scrollHeight;
}
async function chat(mode, text) {
    if (chatBusy[mode]) return;
    const messages = mode === "recipe" ? state.messages : generalMessages;
    messages.push({ role: "user", content: text });
    chatBusy[mode] = true;
    renderMessages(mode);
    const form = $(mode === "recipe" ? "recipe-chat-form" : "general-chat-form");
    form.querySelector("button").disabled = true;
    try {
        const context =
            mode === "recipe"
                ? {
                      source_text: state.source_text,
                      recipes: state.recipes.map((r) => ({ title: r.title, servings: r.servings })),
                      shopping: state.shopping.map((r) => ({
                          name: r.name,
                          quantity_min: r.quantity_min,
                          quantity_max: r.quantity_max,
                          unit: r.unit,
                          unknown_quantity: r.unknown_quantity,
                          excluded: r.excluded,
                          notes: r.notes,
                          budget_estimate: r.budget_estimate || null,
                      })),
                      prices: state.shopping
                          .filter((r) => !r.excluded)
                          .map((r) => ({
                              ingredient: r.name,
                              stores: ["atb", "silpo"].map((store) => {
                                  const p = selectedProduct(r, store);
                                  return p
                                      ? {
                                            store,
                                            name: p.name,
                                            price: p.price,
                                            unit: p.price_unit,
                                            source: p.source,
                                            fetched_at: p.fetched_at,
                                            estimate: estimate(r, p),
                                        }
                                      : { store, status: "Немає підтвердженої ціни" };
                              }),
                          })),
                  }
                : null;
        const r = await api("chat", { mode, messages: messages.slice(-16), context });
        messages.push({ role: "assistant", content: r.answer });
    } catch (e) {
        messages.push({ role: "assistant", content: "Не вдалося відповісти: " + e.message });
        notice(e.message);
    } finally {
        chatBusy[mode] = false;
        form.querySelector("button").disabled = false;
        renderMessages(mode);
    }
}
$("extract").onclick = async () => {
    if (extracting) return;
    const text = $("recipe-text").value.trim();
    if (text.length < 15) {
        notice("Вставте повний рецепт або перелік інгредієнтів.");
        return;
    }
    extracting = true;
    $("extract").disabled = true;
    $("extract-progress").classList.remove("hidden");
    $("notice").classList.add("hidden");
    const start = Date.now();
    let timer = setInterval(
        () => ($("extract-time").textContent = Math.floor((Date.now() - start) / 1000) + " с"),
        1000,
    );
    try {
        const r = await api("extract", { text });
        state = {
            recipes: r.recipes,
            shopping: r.shopping,
            prices: {},
            selected: {},
            multipliers: {},
            messages: [],
            source_text: text,
            run_id: r.run_id,
            session_id: null,
        };
        renderRecipes();
        renderShopping();
        renderMessages("recipe");
        notice(`Готово за ${r.usage.seconds.toFixed(1)} с. Перевірте позначені кількості й продукти для подачі.`, true);
    } catch (e) {
        notice(e.message);
    } finally {
        clearInterval(timer);
        extracting = false;
        $("extract").disabled = false;
        $("extract-progress").classList.add("hidden");
        $("extract-time").textContent = "";
    }
};
async function fetchPrices(refresh = false) {
    if (pricing) return;
    const rows = state.shopping.filter((r) => !r.excluded);
    if (!rows.length) {
        notice("Спочатку додайте продукти до списку.");
        return;
    }
    pricing = true;
    const priceState = state;
    const budgetPromise = prepareBudget();
    $("extract").disabled = true;
    $("fetch-prices").disabled = true;
    $("refresh-prices").disabled = true;
    try {
        for (let i = 0; i < rows.length; i += 3) {
            $("price-progress").textContent = `Перевіряємо ${i + 1}–${Math.min(i + 3, rows.length)} із ${rows.length}…`;
            const r = await api("prices", { ingredients: rows.slice(i, i + 3), refresh });
            if (state !== priceState) return;
            for (const [id, entries] of Object.entries(r.items)) {
                for (const store of Object.keys(entries)) {
                    const manual = state.prices[id]?.[store]?.products?.filter((p) => p.source === "manual") || [];
                    entries[store].products.push(...manual);
                }
                state.prices[id] = entries;
            }
            renderShopping();
        }
        $("price-progress").textContent = "Формуємо попередній кошик…";
        await budgetPromise;
        renderShopping();
        $("price-progress").textContent =
            "Оновлено " + new Date().toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" });
        notice("Пошук завершено. Звірте запропоновані товари та фасування.", true);
    } catch (e) {
        notice(e.message);
        $("price-progress").textContent = "Не завершено";
    } finally {
        pricing = false;
        $("extract").disabled = extracting;
        $("fetch-prices").disabled = false;
        $("refresh-prices").disabled = false;
    }
}
$("fetch-prices").onclick = () => fetchPrices(false);
$("refresh-prices").onclick = () => fetchPrices(true);
$("shopping-list").onclick = (e) => {
    const edit = e.target.closest("[data-edit]");
    if (edit) return openEdit(edit.dataset.edit);
    const choice = e.target.closest("[data-candidates]");
    if (choice) return openCandidates(choice.dataset.candidates, choice.dataset.store);
};
$("shopping-list").onchange = async (e) => {
    if (e.target.dataset.pantry) {
        const row = state.shopping.find((r) => r.id === e.target.dataset.pantry);
        row.excluded = e.target.checked;
        for (const r of state.recipes)
            for (const i of r.ingredients)
                if (row.sources.some((s) => s.recipe === r.title && s.quote === i.source_quote))
                    i.excluded = row.excluded;
        try {
            await aggregate();
            renderRecipes();
        } catch (err) {
            notice(err.message);
        }
    }
};
$("recipe-cards").onchange = async (e) => {
    try {
        if (e.target.dataset.multiplier) {
            const value = Number(e.target.value);
            if (!Number.isFinite(value) || value < 0.1 || value > 20)
                throw new Error("Множник має бути від 0.1 до 20.");
            state.multipliers[e.target.dataset.multiplier] = value;
            state.budget_estimates = {};
            for (const o of Object.values(state.overrides || {})) {
                o.needs_review = true;
                o.notes = [...(o.notes || []), "Порції змінено: перевірте сумарне уточнення."];
            }
            await aggregate();
        }
        if (e.target.dataset.ingredient) {
            for (const r of state.recipes) {
                const i = r.ingredients.find((x) => x.id === e.target.dataset.ingredient);
                if (i) i.excluded = !e.target.checked;
            }
            await aggregate();
        }
    } catch (err) {
        notice(err.message);
    }
};
function openEdit(id) {
    editRow = state.shopping.find((r) => r.id === id);
    $("edit-name").value = editRow.name;
    $("edit-min").value = editRow.quantity_min ?? "";
    $("edit-max").value = editRow.quantity_max ?? "";
    $("edit-unit").value = editRow.unit;
    $("edit-query").value = editRow.query;
    $("edit-dialog").showModal();
}
$("edit-form").onsubmit = (e) => {
    if (e.submitter?.value !== "save") return;
    e.preventDefault();
    const low = $("edit-min").value ? Number($("edit-min").value) : null;
    const high = $("edit-max").value ? Number($("edit-max").value) : low;
    if (low !== null && (low <= 0 || high < low)) {
        notice("Перевірте діапазон кількості.");
        return;
    }
    Object.assign(editRow, {
        name: $("edit-name").value.trim(),
        query: $("edit-query").value.trim(),
        quantity_min: low,
        quantity_max: high,
        unit: $("edit-unit").value,
        unknown_quantity: low === null,
        needs_review: false,
    });
    editRow.notes.push("Уточнено користувачем.");
    state.overrides ??= {};
    state.overrides[editRow.id] = {
        name: editRow.name,
        query: editRow.query,
        quantity_min: low,
        quantity_max: high,
        unit: editRow.unit,
        unknown_quantity: editRow.unknown_quantity,
        needs_review: false,
        notes: editRow.notes,
    };
    if (state.budget_estimates) delete state.budget_estimates[editRow.id];
    editRow.budget_estimate = null;
    delete state.prices[editRow.id];
    delete state.selected[editRow.id];
    $("edit-dialog").close();
    renderShopping();
    notice("Уточнення збережено. Для зміненого продукту оновіть ціни.", true);
};
function openCandidates(id, store) {
    candidateTarget = { id, store };
    const row = state.shopping.find((r) => r.id === id);
    $("candidate-title").textContent = (store === "atb" ? "АТБ" : "Сільпо") + " · " + row.name;
    renderCandidates();
    $("candidate-dialog").showModal();
}
function renderCandidates() {
    const { id, store } = candidateTarget;
    const row = state.shopping.find((r) => r.id === id);
    const ps = state.prices[id]?.[store]?.products || [];
    const selected = selectedProduct(row, store);
    $("candidate-list").innerHTML = ps.length
        ? ps
              .map(
                  (p) =>
                      `<div class="candidate${p.id === selected?.id ? " selected" : ""}"><h3>${esc(p.name)}</h3><p>${esc(p.package_label || "Фасування не визначене")} · ${formatTime(p.fetched_at)}</p><div><strong>${money(p.price)} / ${esc(p.price_unit)}</strong><button class="outline" data-pick="${p.id}">Обрати</button></div><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">Переглянути в магазині</a></div>`,
              )
              .join("")
        : '<p class="muted">Немає відповідних товарів. Спробуйте змінити пошукову назву продукту.</p>';
    $("manual-name").value = row.name;
    $("manual-price").value = "";
    $("manual-pack").value = "";
    $("manual-url").value = "";
}
$("candidate-list").onclick = (e) => {
    const b = e.target.closest("[data-pick]");
    if (!b) return;
    const { id, store } = candidateTarget;
    state.selected[id] ??= {};
    state.selected[id][store] = b.dataset.pick;
    $("candidate-dialog").close();
    renderShopping();
};
$("candidate-close").onclick = () => $("candidate-dialog").close();
$("manual-add").onclick = () => {
    const { id, store } = candidateTarget;
    const name = $("manual-name").value.trim();
    const price = Number($("manual-price").value);
    let url;
    try {
        url = new URL($("manual-url").value);
    } catch {
        notice("Додайте посилання на товар магазину.");
        return;
    }
    const allowed = store === "atb" ? ["www.atbmarket.com", "atbmarket.com"] : ["silpo.ua", "www.silpo.ua"];
    if (
        url.protocol !== "https:" ||
        !allowed.includes(url.hostname) ||
        !name ||
        !Number.isFinite(price) ||
        price <= 0
    ) {
        notice("Перевірте назву, ціну й посилання обраного магазину.");
        return;
    }
    const pack = $("manual-pack").value.trim();
    const [q, u] = packAmount(pack);
    const p = {
        id: "manual-" + Date.now(),
        name,
        price,
        url: url.href,
        weighted: false,
        price_unit: "уп.",
        package_quantity: q,
        package_unit: u,
        package_label: pack,
        step: 1,
        stock: null,
        source: "manual",
        fetched_at: new Date().toISOString(),
    };
    state.prices[id] ??= {};
    state.prices[id][store] ??= { products: [], status: "manual", message: "" };
    state.prices[id][store].products.unshift(p);
    state.selected[id] ??= {};
    state.selected[id][store] = p.id;
    $("candidate-dialog").close();
    renderShopping();
};
function listText() {
    return state.shopping
        .filter((r) => !r.excluded)
        .map((r) => `☐ ${r.name}: ${quantity(r)}`)
        .join("\n");
}
$("copy-list").onclick = async () => {
    try {
        await navigator.clipboard.writeText(listText());
        notice("Список скопійовано.", true);
    } catch {
        notice("Браузер не дозволив копіювання. Скористайтеся завантаженням.");
    }
};
$("download-list").onclick = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(
        new Blob(["Список покупок\nЖитомир\n\n" + listText()], { type: "text/plain;charset=utf-8" }),
    );
    a.download = "shopping-list.txt";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
async function history() {
    try {
        const r = await api("history");
        $("history").innerHTML = r.sessions.length
            ? r.sessions
                  .map(
                      (s) =>
                          `<div class="history-item"><button data-session="${esc(s.id)}">${esc(s.title)}<br><small>${formatTime(s.updated)}</small></button><button class="delete" data-delete="${esc(s.id)}" title="Видалити список" aria-label="Видалити ${esc(s.title)}">×</button></div>`,
                  )
                  .join("")
            : "<p>Тут будуть ваші збережені списки.</p>";
    } catch (e) {
        notice(e.message);
    }
}
$("save-session").onclick = async () => {
    try {
        const r = await api("session", {
            id: state.session_id,
            title: state.recipes.map((r) => r.title).join(" + "),
            data: state,
        });
        state.session_id = r.id;
        await history();
        notice("Список збережено на цьому комп’ютері.", true);
    } catch (e) {
        notice(e.message);
    }
};
$("history").onclick = async (e) => {
    try {
        const open = e.target.closest("[data-session]");
        if (open) {
            state = await api("session?id=" + encodeURIComponent(open.dataset.session));
            state.session_id = open.dataset.session;
            await aggregate();
            $("recipe-text").value = state.source_text;
            updateCount();
            renderRecipes();
            renderShopping();
            renderMessages("recipe");
            showView("recipes");
        }
        const del = e.target.closest("[data-delete]");
        if (del && confirm("Видалити цей збережений список?")) {
            await api("delete-session", { id: del.dataset.delete });
            await history();
        }
    } catch (err) {
        notice(err.message);
    }
};
$("new-session").onclick = () => {
    if (
        (state.recipes.length || $("recipe-text").value) &&
        !confirm("Почати новий список? Незбережені зміни буде скинуто.")
    )
        return;
    state = {
        recipes: [],
        shopping: [],
        prices: {},
        selected: {},
        multipliers: {},
        messages: [],
        source_text: "",
        run_id: "",
        session_id: null,
    };
    $("recipe-text").value = "";
    updateCount();
    renderRecipes();
    renderShopping();
    renderMessages("recipe");
    showView("recipes");
};
function showView(view) {
    document.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    $("recipes-view").classList.toggle("hidden", view !== "recipes");
    $("chat-view").classList.toggle("hidden", view !== "chat");
    $("page-title").textContent = view === "recipes" ? "Від рецепта до покупок" : "Від рецепта до покупок";
}
document.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => showView(b.dataset.view)));
for (const mode of ["recipe", "general"]) {
    $(mode + "-chat-form").onsubmit = (e) => {
        e.preventDefault();
        const box = $(mode === "recipe" ? "recipe-question" : "general-question");
        const text = box.value.trim();
        if (!text) return;
        box.value = "";
        chat(mode, text);
    };
}
// document.querySelectorAll(".quick-questions button").forEach((b) => (b.onclick = () => chat("recipe", b.textContent)));
// $("clear-chat").onclick = () => {
//     generalMessages = [];
//     renderMessages("general");
// };
function updateCount() {
    $("char-count").textContent = $("recipe-text").value.length.toLocaleString("uk-UA") + " символів";
}
$("recipe-text").oninput = updateCount;
// $("clear-input").onclick = () => {
//     $("recipe-text").value = "";
//     updateCount();
// };
$("load-file").onclick = () => $("text-file").click();
$("text-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > 160000) {
        notice("Файл завеликий. Вставте текст до 42 000 символів.");
        return;
    }
    $("recipe-text").value = await f.text();
    updateCount();
};
$("measure-open").onclick = async () => {
    $("measure-case").value = state.recipes.map((r) => r.title).join(" + ");
    $("measure-dialog").showModal();
    try {
        const r = await api("measurements");
        $("measurement-history").textContent = r.records.length
            ? "Записано вимірювань: " +
              r.records.length +
              ". Остання економія часу: " +
              r.records.at(-1).saved_percent +
              "%."
            : "Поки без вимірювань. Не використовуйте приблизні чи вигадані значення.";
    } catch {}
};
$("measure-close").onclick = () => $("measure-dialog").close();
$("measure-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
        const r = await api("measurement", {
            case: $("measure-case").value,
            before_seconds: Number($("measure-before").value),
            after_seconds: Number($("measure-after").value),
            notes: $("measure-notes").value,
            run_id: state.run_id,
        });
        $("measure-dialog").close();
        notice("Вимірювання збережено. Економія часу: " + r.saved_percent + "%.", true);
    } catch (err) {
        notice(err.message);
    }
};
(async () => {
    history();
    try {
        const r = await api("health");
        $("model-status").textContent = r.ready ? "Модель готова · локально" : "Запустіть Ollama та встановіть модель";
        $("model-status").classList.toggle("error", !r.ready);
        //for (const store of ["atb", "silpo"]) $(store + "-context").textContent = r.stores[store].city + " · ";
    } catch {
        notice("Не вдалося підключитися до локального сервера.");
    }
})();

$("category-filter").onchange = renderShopping;
$("suggest-close").onclick = () => $("suggest-dialog").close();
$("suggest-amounts").onclick = async () => {
    const button = $("suggest-amounts");
    button.disabled = true;
    button.textContent = "Готуємо припущення…";
    try {
        const r = await api("suggest", { ingredients: state.shopping, source_text: state.source_text });
        suggestions = r.suggestions;
        $("suggestions-list").innerHTML = suggestions.length
            ? suggestions
                  .map((s, i) => {
                      const row = state.shopping.find((x) => x.id === s.id);
                      return `<div class="suggestion"><label class="suggestion-check"><input type="checkbox" data-accept="${i}"><strong>${esc(row.name)}</strong></label><p class="small-note">У рецепті: ${esc(quantity(row))}</p><div class="suggestion-values"><input type="number" min="0.001" step="any" value="${s.quantity_min}" data-low="${i}" aria-label="Мінімум для ${esc(row.name)}"><span>–</span><input type="number" min="0.001" step="any" value="${s.quantity_max}" data-high="${i}" aria-label="Максимум для ${esc(row.name)}"><select data-unit="${i}" aria-label="Одиниця для ${esc(row.name)}">${["г", "мл", "шт"].map((u) => `<option ${u === s.unit ? "selected" : ""}>${u}</option>`).join("")}</select></div><p class="estimate-reason">${esc(s.reason)}</p></div>`;
                  })
                  .join("")
            : "<p>Немає пропозицій. Можливо, усі кількості вже визначені або моделі недостатньо даних. Уточніть потрібний рядок вручну.</p>";
        $("suggest-dialog").showModal();
    } catch (e) {
        notice(e.message);
    } finally {
        button.disabled = false;
        button.textContent = "✦ Запропонувати кількості";
    }
};
$("apply-suggestions").onclick = () => {
    let accepted = 0;
    state.overrides ??= {};
    for (let i = 0; i < suggestions.length; i++) {
        if (!document.querySelector(`[data-accept="${i}"]`).checked) continue;
        const s = suggestions[i];
        const row = state.shopping.find((x) => x.id === s.id);
        const low = Number(document.querySelector(`[data-low="${i}"]`).value);
        const high = Number(document.querySelector(`[data-high="${i}"]`).value);
        const unit = document.querySelector(`[data-unit="${i}"]`).value;
        if (!Number.isFinite(low) || !Number.isFinite(high) || low <= 0 || high < low) {
            notice("Перевірте діапазон для " + row.name);
            return;
        }
        const original = row.original_quantity || quantity(row);
        const patch = {
            quantity_min: low,
            quantity_max: high,
            unit,
            unknown_quantity: false,
            needs_review: false,
            is_estimate: true,
            original_quantity: original,
            estimate_reason: s.reason,
            notes: [...row.notes, "AI-оцінка прийнята користувачем: " + s.reason],
        };
        Object.assign(row, patch);
        state.overrides[row.id] = { ...(state.overrides[row.id] || {}), ...patch };
        accepted++;
    }
    $("suggest-dialog").close();
    renderShopping();
    notice(
        accepted ? `Застосовано оцінок: ${accepted}. Кошторис за ними приблизний.` : "Жодну пропозицію не застосовано.",
        true,
    );
};

$("measure-small").onclick = () => $("measure-open").click();

async function prepareBudget() {
    const targetState = state;
    const candidates = state.shopping.filter(
        (r) =>
            !r.excluded &&
            !/сіль|перець|лавр|паприк|трав|олія|кетчуп|соус|цукор/i.test(r.name) &&
            (r.quantity_max === null || r.unknown_quantity || !["г", "мл"].includes(r.unit)) &&
            !state.budget_estimates?.[r.id],
    );
    if (!candidates.length) return;
    $("price-progress").textContent = "Оцінюємо вагу продуктів для кошика…";
    try {
        const r = await api("suggest", { ingredients: candidates, source_text: state.source_text });
        if (state !== targetState) return;
        state.budget_estimates ??= {};
        for (const suggestion of r.suggestions) {
            state.budget_estimates[suggestion.id] = suggestion;
            const row = state.shopping.find((x) => x.id === suggestion.id);
            if (row) row.budget_estimate = suggestion;
        }
        renderShopping();
    } catch (e) {
        notice(
            "Ціни знайдені, але автоматично оцінити вагу не вдалося. Можна відкрити оцінки або змінити кількість вручну.",
        );
    }
}
