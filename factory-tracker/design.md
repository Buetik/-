# ПроизводствоТрекер — Design Document

## App Overview
Industrial production tracking app for factory environments. Russian UI, high-contrast dark theme, offline-first with AsyncStorage persistence.

## Color Palette (Industrial Dark Theme)
- **Background**: `#1E252B` (Dark Slate Gray)
- **Surface/Cards**: `#2A333C` (Medium Slate Gray)
- **Primary/Accent**: `#FF6B00` (Safety Orange / Amber)
- **Foreground/Text**: `#FFFFFF` (High-readability White)
- **Muted Text**: `#A0AAB2` (Secondary Light Gray)
- **Border**: `#3A4550`
- **Error**: `#F87171`
- **Success**: `#4ADE80`

## Screen List

### 1. Главная (Dashboard) — `app/(tabs)/index.tsx`
**Content:**
- Top App Bar with current date (ДД.ММ.ГГГГ)
- Summary Card: "Итого за сегодня: X шт."
- FlatList of today's production reports (Name, Quantity, Time)
- Empty state: "Сегодня отчетов еще не было"
- FAB (+) → navigates to New Report screen

### 2. Конструкции (Structures) — `app/(tabs)/structures.tsx`
**Content:**
- Top App Bar: "Справочник конструкций"
- 2-column grid of structure cards (image + name)
- Empty state: "Конструкции еще не добавлены"
- FAB (+) → opens Add Structure bottom sheet/modal
- Modal form: name field + photo picker + save button

### 3. Новый отчет (New Report) — `app/new-report.tsx`
**Content:**
- Top App Bar: "Добавить отчет" + back arrow
- Date picker field (defaults to today)
- Structure dropdown (from saved structures)
- Quantity number input
- Full-width "Сохранить отчет" button
- Validation error states under each field

### 4. Отчеты (Export/Reports) — `app/(tabs)/reports.tsx`
**Content:**
- Top App Bar: "Выгрузка отчетов"
- Date range filters: "Дата с" / "Дата по"
- View switcher: "Обычный текст" | "Таблица"
- Scrollable filtered report content
- Fixed "Скопировать отчет" button

## Navigation Structure
- **Bottom Tab Bar** (3 tabs):
  - Главная (home icon)
  - Конструкции (grid/category icon)
  - Отчеты (chart/document icon)
- **Stack Navigation** for New Report screen (modal push from Dashboard FAB)

## Key User Flows
1. **Add Structure**: Structures tab → FAB → Fill name + photo → Сохранить → Grid updates
2. **Add Report**: Dashboard FAB → Select date + structure + quantity → Сохранить → Back to Dashboard with updated summary
3. **Export Report**: Reports tab → Set date range → Choose view mode → Скопировать отчет → Clipboard

## Data Architecture (AsyncStorage, offline-first)
- `structures`: Array of `{ id, name, photoUri }`
- `productionReports`: Array of `{ id, date, structureId, structureName, quantity }`
- Context + useReducer for global state management
- Persist to AsyncStorage on every mutation

## Typography
- Headers: 18-20px, bold, white
- Body: 14-16px, white
- Secondary: 13-14px, muted gray
- Line height: 1.4× font size
