# -*- coding: utf-8 -*-
"""
تطبيق إدارة التعاميم المدرسية وتوزيع المهام تلقائياً (Streamlit + Google Gemini).
"""
import io
import os
import json
import time
from datetime import datetime, timedelta

import streamlit as st

from employees import (
    EMPLOYEES,
    DEFAULT_DELEGATE_FOR_PRINCIPAL,
    ADMIN_GROUP_NAME,
    TEACHERS_GROUP_NAME,
    PARENTS_GROUP_NAME,
    SCHOOL_NAME,
    SCHOOL_NAME_ALIASES,
)

# ============================================================================
#  إعدادات الصفحة (RTL عربي)
# ============================================================================
st.set_page_config(page_title="توزيع التعاميم المدرسية", page_icon="\U0001F4EC", layout="wide")

st.markdown(
    """
    <style>
    html, body, [class*="css"] { direction: rtl; text-align: right; }
    .stTextArea textarea { direction: rtl; text-align: right; }
    .stCode, code { direction: rtl; text-align: right; }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_gemini_key():
    """يجلب مفتاح Gemini من secrets أو متغيرات البيئة إن وجد."""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
        if "GOOGLE_API_KEY" in st.secrets:
            return str(st.secrets["GOOGLE_API_KEY"]).strip()
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", "")).strip()


def employees_as_text(employees):
    """يحوّل قائمة الموظفين إلى نص (مع استثناء المدير)."""
    lines = []
    for i, e in enumerate(employees, start=1):
        if e.get("is_principal"):
            continue  # استثناء المدير نهائياً
        tasks = "، ".join(e.get("tasks", []))
        role = e.get("role", "")
        lines.append(f"{i}) الاسم: {e['name']} | المسمى: {role} | المهام: {tasks}")
    return "\n".join(lines)


ANALYSIS_SYSTEM_PROMPT = """أنت مساعد إداري ذكي لمدرسة. مهمتك تحليل التعاميم الرسمية بدقة.
قواعد صارمة:
1) لخّص التعميم بإيجاز.
2) استخرج المطلوب بدقة كنقاط عملية.
3) حدّد الموعد النهائي بصيغة ISO إن أمكن، وإلا اتركه فارغاً.
4) وزّع المهمة على الموظف المختص بناءً على مهامهم فقط.
5) مهم جداً: مدير المدرسة (أنس آل طويلب) مستثنى تماماً من أي توجيه تنفيذي. الأولوية دائماً للاختصاص: إذا كان موضوع التعميم يخص اختصاص موظف محدد (مثل التوجيه الطلابي ← هاني ومنير، أو الخطة التشغيلية/التقويم الذاتي ← حسين آل درويش) فوجّهه للمختص حتى لو كان التعميم موجهاً شكلياً لـ«مديري ومديرات المدارس». أمّا إذا كان التعميم عاماً أو خاصاً بالمدير/القيادة المدرسية ولا يخص اختصاص موظف آخر بالاسم، فوجّه المهمة إلى أكبر بن عبد العظيم آل مبارك (نائب المدير).
6) لا تخترع موظفين غير موجودين (يُسمح فقط بالاسم الجماعي «الإخوة الإداريون بالمدرسة» عند انطباق القاعدة 10).
7) التحقق من المدارس المستهدفة: إذا ذكر التعميم أسماء مدارس محددة موجه لها بالتنفيذ، استخرجها كلها. وإذا لم يذكر التعميم أي مدارس محددة (موجه للجميع) فاعتبر القائمة فارغة.
8) قاعدة التوجيه الطلابي (مهمة): أي عمل متعلق بالتوجيه/الإرشاد الطلابي يتطلب إدخالاً أو استكمالاً أو رصداً أو توثيقاً للبيانات في نظام نور يُوجَّه مباشرةً إلى الموجّهين الطلابيين أنفسهم (هاني آل عبيد ومنير آل ناس)، ولا يُوجَّه إلى علي الصفار (مشرف فقط).
9) قاعدة توجيه الدعوات والحضور: إذا كان التعميم دعوة لحضور ورشة/لقاء/برنامج/مؤتمر، وجّه الدعوة للموظف المعني بموضوعها حسب اختصاصه: «التقويم الذاتي/الخطة التشغيلية» ← حسين آل درويش؛ «التوجيه الطلابي/الإرشاد» ← هاني ومنير؛ «الوعي الفكري» ← علي الصفار؛ «إنجاز السعودية/مواهب الطلاب» ← أحمد آل غزوي؛ «المجال الرياضي/التربية البدنية» ← معلمو التربية البدنية. وإن كان عاماً للمدير/لمديري المدارس فأكبر آل مبارك.
10) قاعدة الإداريين: إذا كان التعميم موجّهاً لجميع شاغلي الوظائف الإدارية / الكوادر الإدارية / الإداريين بالمدرسة بشكل عام (مثل الترشيح لبرامج تدريبية للإداريين، أو تعميم فرصة على الإداريين)، فاجعل employee_name = "الإخوة الإداريون بالمدرسة" (مجموعة واحدة) وضع المطلوب في task_detail.
11) قاعدة المعلمين والمعلمات (مهمة جداً): كثير من التعاميم تُوجّه شكلاً إلى «مديري ومديرات المدارس» لكن المضمون والمقصود هم المعلمون والمعلمات. فإذا كان المطلوب هو حثّ المعلمين والمعلمات أو إبلاغهم أو دعوتهم أو تشجيعهم أو التأكيد على حضورهم أو مشاركتهم في أي شيء (ورشة عمل، لقاء، اجتماع، فعالية، دورة، برنامج، مسابقة، هاكاثون، تدريب، تسجيل)، أو كان الخطاب موجّهاً أصلاً للمعلمين والمعلمات، فاجعل employee_name = "المعلمون والمعلمات بالمدرسة" (مجموعة واحدة) وضع المطلوب في task_detail. (هذه القاعدة تسبق توجيه المهمة للنائب حين يكون جمهور التعميم المقصود هم المعلمون والمعلمات).
12) قاعدة الطلاب (مهمة جداً): كثير من التعاميم تُوجّه شكلاً إلى المدير/«مديري ومديرات المدارس» لكن المضمون والمقصود هم الطلاب (مثل: توعية الطلاب، حثّ الطلاب على التسجيل/المشاركة، مسابقة أو برنامج أو فعالية للطلاب). ففي هذه الحالة اجعل employee_name = "أولياء أمور الطلاب" (مجموعة واحدة — لأن رسائل الطلاب تُرسل على قروب أولياء الأمور) وضع المطلوب في task_detail. واستخرج الفئة المستهدفة من الطلاب في الحقل student_scope: إن كان التعميم لجميع الطلاب/الفصول اجعل all_classes=true وgrades فارغة؛ وإن خصّ صفوفاً محددة (مثل الصف الثالث الابتدائي) فضعها في grades واجعل all_classes=false. ملاحظة: مدرستنا ابتدائية، فإن ذكر التعميم مدى واسعاً (مثل الثالث الابتدائي حتى الثالث الثانوي) فاذكر في grades الصفوف التي تخصّ المرحلة الابتدائية فقط. (إن تضمّن التعميم أيضاً دوراً للمعلمين فيمكن إضافة تكليف ثانوٍ لـ"المعلمون والمعلمات بالمدرسة").
13) أعد الناتج بصيغة JSON فقط."""
# __PART1_END__


def build_user_prompt(circular_text, employees_text):
    aliases = "، ".join([SCHOOL_NAME] + SCHOOL_NAME_ALIASES)
    return (
        "هذه قائمة الموظفين ومهامهم (المدير مستثنى سلفاً):\n"
        + employees_text
        + "\n\nاسم مدرستنا (وصيغه المحتملة): "
        + aliases
        + "\n\n--- نص التعميم ---\n"
        + circular_text
        + "\n--- نهاية التعميم ---\n\n"
        + 'ملاحظة: الحقل school_included يعني هل مدرستنا ضمن targeted_schools؟ '
        + 'إن كانت targeted_schools فارغة (لا توجد مدارس محددة) اجعل school_included = true.\n\n'
        + 'ملاحظة أخرى: الحقل directed_to_official خاص بالتنبيه. اجعل flag=true إذا ذُكر في نص التعميم صراحةً '
        + 'أحد هؤلاء بالاسم (أنس آل طويلب، أكبر آل مبارك، سعيد آل شيب، علي الصفار) '
        + 'أو وُجّه التعميم/الخطاب إلى «وكيل المدرسة» أو «الوكيل» بشكل عام. '
        + 'وضع في names_found الأسماء أو الصفات التي وُجدت، وإلا اجعل flag=false والقائمة فارغة.\n\n'
        + 'أعد JSON بالشكل التالي تماماً (بدون أي تعليقات):\n'
        + '{"summary": "...", "requirements": ["..."], '
        + '"deadline": "YYYY-MM-DDTHH:MM أو فارغ", '
        + '"deadline_text": "نص الموعد كما ورد", '
        + '"targeted_schools": ["أسماء المدارس المذكورة صراحة في التعميم، أو قائمة فارغة"], '
        + '"school_included": true, '
        + '"directed_to_official": {"flag": false, "names_found": []}, '
        + '"student_scope": {"all_classes": false, "grades": []}, '
        + '"assignments": [{"employee_name": "اسم من القائمة", '
        + '"reason": "سبب الاختيار", "task_detail": "المطلوب بالتحديد"}]}'
    )


def generate_with_retry(gmodel, parts, tries=4):
    """إعادة محاولة تلقائية عند أخطاء الازدحام 503/429 (انتظار متدرّج)."""
    delays = [3, 6, 12, 24]
    last_err = None
    for i in range(tries):
        try:
            return gmodel.generate_content(parts)
        except Exception as ex:
            last_err = ex
            msg = str(ex)
            if ("503" in msg or "UNAVAILABLE" in msg or "429" in msg or "overloaded" in msg.lower()) and i < tries - 1:
                time.sleep(delays[min(i, len(delays) - 1)])
                continue
            raise
    if last_err:
        raise last_err


def analyze_circular(circular_text, image_payloads, employees_text, api_key, model):
    """يستدعي Google Gemini لتحليل التعميم. يدعم النص أو عدة صور."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    gmodel = genai.GenerativeModel(
        model_name=model,
        system_instruction=ANALYSIS_SYSTEM_PROMPT,
        generation_config={
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    )

    if image_payloads:
        parts = [build_user_prompt("(انظر الصور/الصورة المرفقة واعتبرها تعميماً واحداً)", employees_text)]
        for img in image_payloads:
            parts.append({"mime_type": img["mime_type"], "data": img["data"]})
    else:
        parts = [build_user_prompt(circular_text, employees_text)]

    resp = generate_with_retry(gmodel, parts)
    return json.loads(resp.text)


def enforce_principal_exclusion(assignments):
    """طبقة حماية برمجية: إعادة توجيه أي مهمة وصلت للمدير."""
    principals = {e["name"] for e in EMPLOYEES if e.get("is_principal")}
    for a in assignments:
        if a.get("employee_name") in principals:
            a["employee_name"] = DEFAULT_DELEGATE_FOR_PRINCIPAL
            a["reason"] = "(أُعيد التوجيه للنائب لاستثناء المدير) " + a.get("reason", "")
    return assignments


def build_message(employee_names, task_detail, deadline_text, deadline_iso, subject="", extra_notes=None):
    deadline_line = deadline_text or deadline_iso or "غير محدد"

    if isinstance(employee_names, (list, tuple)):
        names = [str(n).strip() for n in employee_names if str(n).strip()]
    else:
        names = [str(employee_names).strip()] if str(employee_names).strip() else []

    if isinstance(task_detail, (list, tuple)):
        items = [str(x).strip() for x in task_detail if str(x).strip()]
    else:
        raw = str(task_detail or "").strip()
        if "\n" in raw:
            items = [p.strip(" -\u2022\t") for p in raw.split("\n") if p.strip(" -\u2022\t")]
        else:
            items = [raw] if raw else []

    if items:
        tasks_block = "\n".join(f"{n}\u0640   {t}" for n, t in enumerate(items, start=1))
    else:
        tasks_block = "\u0640"

    def _salutation(n):
        nm = n.strip()
        if nm == ADMIN_GROUP_NAME:
            return f"*{nm}* المحترمون،"
        if nm == TEACHERS_GROUP_NAME:
            return f"الأساتذة الكرام *{nm}* المحترمون،"
        if nm == PARENTS_GROUP_NAME:
            return f"الأفاضل *{nm}* المحترمون،"
        if nm.startswith("معلمو") or nm.startswith("معلمي"):
            return f"الأساتذة *{nm}* المحترمون،"
        return f"الأستاذ الفاضل/ *{nm}* المحترم،"

    lines = [_salutation(n) for n in names]
    if subject:
        lines.append(f"بشأن: {subject}")
    lines += [
        "*المطلوب:*",
        tasks_block,
        f"\U0001F5D3\uFE0F *الموعد النهائي:* {deadline_line}",
    ]
    if extra_notes:
        for note in extra_notes:
            if str(note).strip():
                lines.append(str(note).strip())
    return "\n".join(lines)
# __PART2_END__


def extract_pdf_text(file_bytes):
    """استخراج نص من ملف PDF (إن أمكن)."""
    try:
        import pdfplumber
        text = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text.append(page.extract_text() or "")
        return "\n".join(text).strip()
    except Exception:
        return ""


# ============================================================================
#  عرض النتيجة والتنبيهات والرسائل
# ============================================================================
def render_result(result):
    summary = result.get("summary", "")
    requirements = result.get("requirements", []) or []
    deadline_iso = (result.get("deadline") or "").strip()
    deadline_text = (result.get("deadline_text") or "").strip()
    targeted = result.get("targeted_schools", []) or []
    school_included = result.get("school_included", True)
    directed = result.get("directed_to_official", {}) or {}
    student_scope = result.get("student_scope", {}) or {}
    assignments = result.get("assignments", []) or []

    assignments = enforce_principal_exclusion(assignments)

    # --- التنبيهات قبل التوزيع ---
    if directed.get("flag"):
        found = "، ".join(directed.get("names_found", []) or []) or "اسم/صفة محددة"
        st.warning(
            f"\U0001F514 تنبيه: التعميم يذكر صراحةً ({found}). "
            "راجع التوزيع يدوياً قبل الإرسال (قد يكون المقصود شخصاً بعينه أو الوكيل)."
        )

    if targeted:
        if school_included:
            st.success(f"\u2705 مدرستنا ({SCHOOL_NAME}) ضمن المدارس المستهدفة.")
        else:
            st.error(
                "\u26A0\uFE0F تنبيه: يبدو أن التعميم موجّه لمدارس محددة ولا تظهر مدرستنا ضمنها:\n• "
                + "\n• ".join(targeted)
                + "\n\nتأكد أن التعميم يخصنا قبل توزيع المهام."
            )

    # --- الملخص ---
    st.subheader("\U0001F4DD ملخص التعميم")
    st.info(summary or "—")
    if requirements:
        st.markdown("**المطلوب العام:**")
        for r in requirements:
            st.markdown(f"- {r}")
    disp_deadline = deadline_text or deadline_iso or "غير محدد"
    st.markdown(f"**\U0001F5D3\uFE0F الموعد النهائي:** {disp_deadline}")

    # --- تذكير بالموعد ---
    if deadline_iso:
        try:
            dl = datetime.fromisoformat(deadline_iso.replace("Z", ""))
            days_left = (dl.date() - datetime.now().date()).days
            if days_left < 0:
                st.error("\u23F0 انتبه: الموعد النهائي قد انتهى!")
            elif days_left == 0:
                st.warning("\u23F0 الموعد النهائي اليوم!")
            elif days_left <= 2:
                st.warning(f"\u23F0 متبقٍ {days_left} يوم على الموعد النهائي.")
            else:
                st.caption(f"\u23F3 متبقٍ {days_left} يوماً على الموعد النهائي.")
        except Exception:
            pass

    st.divider()
    st.subheader("\U0001F4E4 رسائل جاهزة للنسخ (واتساب)")

    if not assignments:
        st.warning("لم يتم تحديد مهام محددة لموظفين من هذا التعميم. راجعه يدوياً.")
        return

    # --- دمج أصحاب نفس المطلوب في رسالة واحدة ---
    groups = {}  # task_detail -> [names]
    order = []
    for a in assignments:
        name = (a.get("employee_name") or "").strip()
        task = (a.get("task_detail") or "").strip()
        if not name:
            continue
        key = task
        if key not in groups:
            groups[key] = []
            order.append(key)
        if name not in groups[key]:
            groups[key].append(name)

    # ملاحظات خاصة برسائل أولياء الأمور (قروب + الفئة المستهدفة)
    def parents_notes():
        notes = ["\U0001F4CC *ملاحظة:* تُرسل هذه الرسالة على قروب أولياء الأمور."]
        grades = student_scope.get("grades", []) or []
        if student_scope.get("all_classes") or not grades:
            notes.append("\U0001F465 *الفئة المستهدفة:* جميع الفصول.")
        else:
            notes.append("\U0001F465 *الفئة المستهدفة:* " + "، ".join(grades) + ".")
        return notes

    for idx, task in enumerate(order, start=1):
        names = groups[task]
        notes = parents_notes() if PARENTS_GROUP_NAME in names else None
        msg = build_message(names, task, deadline_text, deadline_iso, subject=summary, extra_notes=notes)
        st.markdown(f"**\U0001F4CB رسالة {idx} — إلى: {'، '.join(names)}**")
        st.code(msg, language=None)


# ============================================================================
#  الشريط الجانبي: المفتاح والنموذج
# ============================================================================
st.sidebar.header("\u2699\uFE0F الإعدادات")
api_key_input = st.sidebar.text_input(
    "مفتاح Google Gemini API",
    type="password",
    value=get_gemini_key(),
    help="احصل على مفتاح مجاني من https://aistudio.google.com/app/apikey",
)


@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_models(key):
    import google.generativeai as genai
    genai.configure(api_key=key)
    names = []
    for m in genai.list_models():
        if "generateContent" in getattr(m, "supported_generation_methods", []):
            names.append(m.name.replace("models/", ""))
    return names


_fallback = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest"]
_key_clean = str(api_key_input).strip() if api_key_input else ""
model_options = _fallback
if _key_clean and _key_clean.isascii():
    try:
        live = _fetch_models(_key_clean)
        if live:
            flash = [m for m in live if "flash" in m]
            rest = [m for m in live if "flash" not in m]
            latest = [m for m in flash + rest if m.endswith("-latest")]
            others = [m for m in flash + rest if not m.endswith("-latest")]
            model_options = latest + others
    except Exception:
        model_options = _fallback

model_name = st.sidebar.selectbox(
    "النموذج",
    model_options,
    index=0,
    help="هذه النماذج مجلوبة تلقائياً من حسابك بعد إدخال المفتاح، لذا لن تظهر نماذج منتهية.",
)
st.sidebar.divider()
if st.sidebar.button("\U0001F50E عرض النماذج المتاحة لمفتاحي"):
    if not _key_clean or not _key_clean.isascii():
        st.sidebar.error("أدخل مفتاح Gemini صحيحاً أولاً.")
    else:
        try:
            avail = _fetch_models(_key_clean)
            st.sidebar.success("النماذج التي تدعم التحليل:")
            for mname in avail:
                st.sidebar.write(f"\u2022 {mname}")
        except Exception as ex:
            st.sidebar.error(f"تعذر جلب النماذج: {ex}")


# ============================================================================
#  الواجهة الرئيسية
# ============================================================================
st.title("\U0001F4EC توزيع التعاميم المدرسية")
st.write("ارفع التعميم، وسيقوم النظام بتلخيصه وتحديد المطلوب والموعد وتوزيع المهام تلقائياً.")

uploaded = st.file_uploader(
    "ارفع التعميم (PDF أو صورة)",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)
circular_text_input = st.text_area("أو الصق نص التعميم هنا:", height=200)

go = st.button("\U0001F680 حلّل ووزّع المهام", type="primary")

if go:
    api_key = str(api_key_input).strip()
    if not api_key:
        st.error("الرجاء إدخال مفتاح Google Gemini API أولاً.")
    elif not api_key.isascii():
        st.error("مفتاح API غير صحيح (يجب أن يكون بأحرف إنجليزية/أرقام فقط — لا تلصق نصاً عربياً).")
    else:
        # تجميع المدخلات
        text_parts = []
        image_payloads = []
        if uploaded:
            for pf in uploaded:
                data = pf.read()
                lower = pf.name.lower()
                if lower.endswith(".pdf"):
                    txt = extract_pdf_text(data)
                    if txt:
                        text_parts.append(txt)
                    else:
                        st.warning(f"تعذر استخراج نص من الملف: {pf.name} (قد يكون مسوحاً كصورة). جرّب رفعه كصورة.")
                else:
                    mime = "image/png" if lower.endswith(".png") else "image/jpeg"
                    image_payloads.append({"mime_type": mime, "data": data})
        if circular_text_input.strip():
            text_parts.append(circular_text_input.strip())

        combined_text = "\n\n".join(text_parts).strip()

        if not combined_text and not image_payloads:
            st.error("الرجاء رفع تعميم أو إدخال نص.")
        else:
            employees_text = employees_as_text(EMPLOYEES)
            result = None
            with st.spinner("جارٍ التحليل... (قد يستغرق لحظات)"):
                try:
                    result = analyze_circular(
                        combined_text, image_payloads, employees_text, api_key, model_name
                    )
                except Exception as ex:
                    msg = str(ex)
                    if "429" in msg or "quota" in msg.lower() or "insufficient" in msg.lower():
                        st.error(
                            "\u26A0\uFE0F تجاوزت الحد اليومي المجاني لهذا النموذج (20 طلباً في اليوم لكل نموذج).\n\n"
                            "الحلول:\n"
                            "1\u0640 غيّر النموذج من الشريط الجانبي (لكل نموذج حصة مجانية مستقلة) — جرّب gemini-flash-latest.\n"
                            "2\u0640 أو انتظر حتى إعادة تعيين الحد (خلال ~24 ساعة).\n"
                            "3\u0640 أو استخدم مفتاح Gemini من حساب آخر."
                        )
                    elif "401" in msg or "API_KEY_INVALID" in msg or "invalid" in msg.lower():
                        st.error("مفتاح API غير صحيح. تأكد من نسخه كاملاً من aistudio.google.com/app/apikey")
                    elif "404" in msg:
                        st.error("النموذج غير متاح. جرّب نموذجاً آخر من القائمة (يُفضّل الأسماء المنتهية ب\u0640latest).")
                    else:
                        st.error(f"حدث خطأ أثناء التحليل: {ex}")

            if result:
                render_result(result)
# __PART3_END__
