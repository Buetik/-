import React, { useState, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Modal,
  FlatList,
  Platform,
  ToastAndroid,
  Alert,
  Clipboard,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import { useData, formatDate, startOfDay, endOfDay, ProductionReport } from '@/lib/data-context';

const C = {
  bg: '#1E252B',
  surface: '#2A333C',
  primary: '#FF6B00',
  foreground: '#FFFFFF',
  muted: '#A0AAB2',
  border: '#3A4550',
  error: '#F87171',
};

function showToast(message: string) {
  if (Platform.OS === 'android') {
    ToastAndroid.show(message, ToastAndroid.SHORT);
  } else {
    Alert.alert('', message);
  }
}

// ─── Inline Date Picker ───────────────────────────────────────────────────────

interface DatePickerModalProps {
  visible: boolean;
  selectedDate: Date;
  title: string;
  onConfirm: (date: Date) => void;
  onDismiss: () => void;
}

function DatePickerModal({ visible, selectedDate, title, onConfirm, onDismiss }: DatePickerModalProps) {
  const [current, setCurrent] = useState(new Date(selectedDate));
  const [viewYear, setViewYear] = useState(selectedDate.getFullYear());
  const [viewMonth, setViewMonth] = useState(selectedDate.getMonth());

  const MONTHS_RU = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
  ];
  const DAYS_RU = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

  const days = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1);
    const lastDay = new Date(viewYear, viewMonth + 1, 0);
    const startDow = (firstDay.getDay() + 6) % 7;
    const cells: (number | null)[] = [];
    for (let i = 0; i < startDow; i++) cells.push(null);
    for (let d = 1; d <= lastDay.getDate(); d++) cells.push(d);
    return cells;
  }, [viewYear, viewMonth]);

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1); }
    else setViewMonth(m => m - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1); }
    else setViewMonth(m => m + 1);
  };

  const isSelected = (d: number) =>
    current.getDate() === d && current.getMonth() === viewMonth && current.getFullYear() === viewYear;

  const isToday = (d: number) => {
    const t = new Date();
    return t.getDate() === d && t.getMonth() === viewMonth && t.getFullYear() === viewYear;
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onDismiss}>
      <View style={dpStyles.overlay}>
        <View style={dpStyles.container}>
          <Text style={dpStyles.title}>{title}</Text>
          <View style={dpStyles.monthNav}>
            <TouchableOpacity onPress={prevMonth} style={dpStyles.navBtn}>
              <MaterialIcons name="chevron-left" size={24} color={C.foreground} />
            </TouchableOpacity>
            <Text style={dpStyles.monthLabel}>{MONTHS_RU[viewMonth]} {viewYear}</Text>
            <TouchableOpacity onPress={nextMonth} style={dpStyles.navBtn}>
              <MaterialIcons name="chevron-right" size={24} color={C.foreground} />
            </TouchableOpacity>
          </View>
          <View style={dpStyles.daysRow}>
            {DAYS_RU.map((d) => (
              <Text key={d} style={dpStyles.dayHeader}>{d}</Text>
            ))}
          </View>
          <View style={dpStyles.grid}>
            {days.map((d, i) => (
              <TouchableOpacity
                key={i}
                style={[
                  dpStyles.dayCell,
                  d !== null && isSelected(d) && dpStyles.dayCellSelected,
                  d !== null && isToday(d) && !isSelected(d) && dpStyles.dayCellToday,
                ]}
                onPress={() => { if (d !== null) setCurrent(new Date(viewYear, viewMonth, d)); }}
                disabled={d === null}
              >
                {d !== null && (
                  <Text style={[
                    dpStyles.dayText,
                    isSelected(d) && dpStyles.dayTextSelected,
                    isToday(d) && !isSelected(d) && dpStyles.dayTextToday,
                  ]}>
                    {d}
                  </Text>
                )}
              </TouchableOpacity>
            ))}
          </View>
          <View style={dpStyles.actions}>
            <TouchableOpacity style={dpStyles.cancelBtn} onPress={onDismiss}>
              <Text style={dpStyles.cancelText}>Отмена</Text>
            </TouchableOpacity>
            <TouchableOpacity style={dpStyles.confirmBtn} onPress={() => onConfirm(current)}>
              <Text style={dpStyles.confirmText}>Выбрать</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// ─── Main Screen ──────────────────────────────────────────────────────────────

type ViewMode = 'text' | 'table';

export default function ReportsScreen() {
  const { state } = useData();

  const today = new Date();
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);

  const [dateFrom, setDateFrom] = useState(weekAgo);
  const [dateTo, setDateTo] = useState(today);
  const [viewMode, setViewMode] = useState<ViewMode>('text');
  const [dateFromPickerVisible, setDateFromPickerVisible] = useState(false);
  const [dateToPickerVisible, setDateToPickerVisible] = useState(false);

  const filteredReports = useMemo(() => {
    const start = startOfDay(dateFrom.getTime());
    const end = endOfDay(dateTo.getTime());
    return state.reports
      .filter((r) => r.date >= start && r.date <= end)
      .sort((a, b) => a.date - b.date);
  }, [state.reports, dateFrom, dateTo]);

  const totalQuantity = useMemo(
    () => filteredReports.reduce((sum, r) => sum + r.quantity, 0),
    [filteredReports]
  );

  const plainTextContent = useMemo(() => {
    if (filteredReports.length === 0) return 'Нет данных за выбранный период';
    return filteredReports
      .map((r) => `${formatDate(r.date)} — ${r.structureName}: ${r.quantity} шт.`)
      .join('\n');
  }, [filteredReports]);

  const handleCopy = useCallback(() => {
    const content = viewMode === 'text'
      ? plainTextContent
      : filteredReports.length === 0
        ? 'Нет данных за выбранный период'
        : `Дата\tКонструкция\tКол-во\n` +
          filteredReports.map((r) => `${formatDate(r.date)}\t${r.structureName}\t${r.quantity} шт.`).join('\n');

    Clipboard.setString(content);
    showToast('Отчет скопирован в буфер обмена');
  }, [viewMode, plainTextContent, filteredReports]);

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      {/* Top App Bar */}
      <View style={styles.appBar}>
        <Text style={styles.appBarTitle}>Выгрузка отчетов</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        {/* Date Range Filters */}
        <View style={styles.filterCard}>
          <Text style={styles.filterTitle}>Период</Text>
          <View style={styles.filterRow}>
            <View style={styles.filterField}>
              <Text style={styles.filterLabel}>Дата с</Text>
              <TouchableOpacity
                style={styles.dateBtn}
                onPress={() => setDateFromPickerVisible(true)}
                activeOpacity={0.8}
              >
                <MaterialIcons name="calendar-today" size={16} color={C.primary} />
                <Text style={styles.dateBtnText}>{formatDate(dateFrom.getTime())}</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.filterDivider}>
              <Text style={styles.filterDividerText}>—</Text>
            </View>
            <View style={styles.filterField}>
              <Text style={styles.filterLabel}>Дата по</Text>
              <TouchableOpacity
                style={styles.dateBtn}
                onPress={() => setDateToPickerVisible(true)}
                activeOpacity={0.8}
              >
                <MaterialIcons name="calendar-today" size={16} color={C.primary} />
                <Text style={styles.dateBtnText}>{formatDate(dateTo.getTime())}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>

        {/* Stats Summary */}
        <View style={styles.statsRow}>
          <View style={styles.statChip}>
            <Text style={styles.statValue}>{filteredReports.length}</Text>
            <Text style={styles.statLabel}>записей</Text>
          </View>
          <View style={styles.statChip}>
            <Text style={styles.statValue}>{totalQuantity}</Text>
            <Text style={styles.statLabel}>шт. итого</Text>
          </View>
        </View>

        {/* View Mode Switcher */}
        <View style={styles.viewSwitcher}>
          <TouchableOpacity
            style={[styles.switchBtn, viewMode === 'text' && styles.switchBtnActive]}
            onPress={() => setViewMode('text')}
          >
            <MaterialIcons
              name="description"
              size={16}
              color={viewMode === 'text' ? '#FFFFFF' : C.muted}
            />
            <Text style={[styles.switchBtnText, viewMode === 'text' && styles.switchBtnTextActive]}>
              Обычный текст
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.switchBtn, viewMode === 'table' && styles.switchBtnActive]}
            onPress={() => setViewMode('table')}
          >
            <MaterialIcons
              name="table-chart"
              size={16}
              color={viewMode === 'table' ? '#FFFFFF' : C.muted}
            />
            <Text style={[styles.switchBtnText, viewMode === 'table' && styles.switchBtnTextActive]}>
              Таблица
            </Text>
          </TouchableOpacity>
        </View>

        {/* Content */}
        {filteredReports.length === 0 ? (
          <View style={styles.emptyState}>
            <MaterialIcons name="bar-chart" size={48} color={C.muted} />
            <Text style={styles.emptyText}>Нет данных за выбранный период</Text>
          </View>
        ) : viewMode === 'text' ? (
          <View style={styles.textBlock}>
            <Text style={styles.textContent}>{plainTextContent}</Text>
          </View>
        ) : (
          <View style={styles.tableContainer}>
            {/* Table Header */}
            <View style={[styles.tableRow, styles.tableHeader]}>
              <Text style={[styles.tableCell, styles.tableCellDate, styles.tableHeaderText]}>Дата</Text>
              <Text style={[styles.tableCell, styles.tableCellName, styles.tableHeaderText]}>Конструкция</Text>
              <Text style={[styles.tableCell, styles.tableCellQty, styles.tableHeaderText]}>Кол-во</Text>
            </View>
            {filteredReports.map((r, i) => (
              <View
                key={r.id}
                style={[styles.tableRow, i % 2 === 0 ? styles.tableRowEven : styles.tableRowOdd]}
              >
                <Text style={[styles.tableCell, styles.tableCellDate]}>{formatDate(r.date)}</Text>
                <Text style={[styles.tableCell, styles.tableCellName]} numberOfLines={2}>{r.structureName}</Text>
                <Text style={[styles.tableCell, styles.tableCellQty, styles.tableCellQtyText]}>{r.quantity} шт.</Text>
              </View>
            ))}
            {/* Total Row */}
            <View style={[styles.tableRow, styles.tableTotalRow]}>
              <Text style={[styles.tableCell, styles.tableCellDate, styles.tableTotalText]}>Итого</Text>
              <Text style={[styles.tableCell, styles.tableCellName]} />
              <Text style={[styles.tableCell, styles.tableCellQty, styles.tableTotalText]}>{totalQuantity} шт.</Text>
            </View>
          </View>
        )}

        <View style={{ height: 100 }} />
      </ScrollView>

      {/* Copy Button */}
      <View style={styles.footer}>
        <TouchableOpacity style={styles.copyBtn} onPress={handleCopy} activeOpacity={0.85}>
          <MaterialIcons name="content-copy" size={20} color="#FFFFFF" />
          <Text style={styles.copyBtnText}>Скопировать отчет</Text>
        </TouchableOpacity>
      </View>

      <DatePickerModal
        visible={dateFromPickerVisible}
        selectedDate={dateFrom}
        title="Дата с"
        onConfirm={(d) => { setDateFrom(d); setDateFromPickerVisible(false); }}
        onDismiss={() => setDateFromPickerVisible(false)}
      />
      <DatePickerModal
        visible={dateToPickerVisible}
        selectedDate={dateTo}
        title="Дата по"
        onConfirm={(d) => { setDateTo(d); setDateToPickerVisible(false); }}
        onDismiss={() => setDateToPickerVisible(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  appBar: {
    paddingHorizontal: 20,
    paddingVertical: 14,
    backgroundColor: C.surface,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  appBarTitle: { fontSize: 18, fontWeight: '700', color: C.foreground },
  scrollContent: { padding: 16 },

  filterCard: {
    backgroundColor: C.surface,
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: C.border,
    marginBottom: 12,
  },
  filterTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: C.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 12,
  },
  filterRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  filterField: { flex: 1 },
  filterLabel: { fontSize: 11, color: C.muted, marginBottom: 6 },
  filterDivider: { paddingTop: 16 },
  filterDividerText: { color: C.muted, fontSize: 16 },
  dateBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#1A2028',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: C.border,
  },
  dateBtnText: { fontSize: 13, color: C.foreground, fontWeight: '500' },

  statsRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 12,
  },
  statChip: {
    flex: 1,
    backgroundColor: C.surface,
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: C.border,
  },
  statValue: { fontSize: 24, fontWeight: '800', color: C.primary },
  statLabel: { fontSize: 12, color: C.muted, marginTop: 2 },

  viewSwitcher: {
    flexDirection: 'row',
    backgroundColor: '#1A2028',
    borderRadius: 12,
    padding: 4,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: C.border,
  },
  switchBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 10,
    borderRadius: 9,
  },
  switchBtnActive: { backgroundColor: C.primary },
  switchBtnText: { fontSize: 13, fontWeight: '600', color: C.muted },
  switchBtnTextActive: { color: '#FFFFFF' },

  textBlock: {
    backgroundColor: C.surface,
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: C.border,
  },
  textContent: {
    fontSize: 14,
    color: C.foreground,
    lineHeight: 22,
    fontFamily: Platform.OS === 'ios' ? 'Courier New' : 'monospace',
  },

  tableContainer: {
    backgroundColor: C.surface,
    borderRadius: 12,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: C.border,
  },
  tableRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  tableHeader: {
    backgroundColor: '#1A2028',
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  tableHeaderText: { color: C.muted, fontWeight: '700', fontSize: 12, textTransform: 'uppercase' },
  tableRowEven: { backgroundColor: C.surface },
  tableRowOdd: { backgroundColor: '#252E37' },
  tableTotalRow: {
    backgroundColor: '#1A2028',
    borderTopWidth: 1,
    borderTopColor: C.border,
  },
  tableTotalText: { color: C.primary, fontWeight: '700' },
  tableCell: { fontSize: 13, color: C.foreground, lineHeight: 18 },
  tableCellDate: { width: 90 },
  tableCellName: { flex: 1, paddingHorizontal: 8 },
  tableCellQty: { width: 70, textAlign: 'right' },
  tableCellQtyText: { color: C.primary, fontWeight: '600' },

  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
    gap: 12,
  },
  emptyText: { fontSize: 15, color: C.muted, textAlign: 'center' },

  footer: {
    paddingHorizontal: 16,
    paddingVertical: 14,
    paddingBottom: Platform.OS === 'ios' ? 24 : 14,
    backgroundColor: C.bg,
    borderTopWidth: 1,
    borderTopColor: C.border,
  },
  copyBtn: {
    backgroundColor: C.primary,
    borderRadius: 12,
    paddingVertical: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  copyBtnText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF' },
});

const dpStyles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
  },
  container: {
    backgroundColor: C.surface,
    borderRadius: 20,
    padding: 20,
    width: '100%',
    maxWidth: 360,
    borderWidth: 1,
    borderColor: C.border,
  },
  title: {
    fontSize: 17,
    fontWeight: '700',
    color: C.foreground,
    textAlign: 'center',
    marginBottom: 16,
  },
  monthNav: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  navBtn: { padding: 6 },
  monthLabel: { fontSize: 15, fontWeight: '600', color: C.foreground },
  daysRow: { flexDirection: 'row', marginBottom: 6 },
  dayHeader: {
    flex: 1,
    textAlign: 'center',
    fontSize: 12,
    fontWeight: '600',
    color: C.muted,
    paddingVertical: 4,
  },
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  dayCell: {
    width: `${100 / 7}%`,
    aspectRatio: 1,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 20,
  },
  dayCellSelected: { backgroundColor: C.primary },
  dayCellToday: { borderWidth: 1, borderColor: C.primary },
  dayText: { fontSize: 13, color: C.foreground },
  dayTextSelected: { color: '#FFFFFF', fontWeight: '700' },
  dayTextToday: { color: C.primary, fontWeight: '700' },
  actions: { flexDirection: 'row', gap: 12, marginTop: 16 },
  cancelBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: '#1A2028',
    borderWidth: 1,
    borderColor: C.border,
    alignItems: 'center',
  },
  cancelText: { color: C.muted, fontWeight: '600', fontSize: 15 },
  confirmBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: C.primary,
    alignItems: 'center',
  },
  confirmText: { color: '#FFFFFF', fontWeight: '700', fontSize: 15 },
});
