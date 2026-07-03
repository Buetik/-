import React, { useState, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
} from 'react-native';
import MaterialIcons from '@expo/vector-icons/MaterialIcons';

const C = {
  bg: '#1E252B',
  surface: '#2A333C',
  primary: '#FF6B00',
  foreground: '#FFFFFF',
  muted: '#A0AAB2',
  border: '#3A4550',
};

const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];
const DAYS_RU = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

interface DatePickerModalProps {
  visible: boolean;
  selectedDate: Date;
  title?: string;
  onConfirm: (date: Date) => void;
  onDismiss: () => void;
}

export function DatePickerModal({
  visible,
  selectedDate,
  title = 'Выберите дату',
  onConfirm,
  onDismiss,
}: DatePickerModalProps) {
  const [current, setCurrent] = useState(new Date(selectedDate));
  const [viewYear, setViewYear] = useState(selectedDate.getFullYear());
  const [viewMonth, setViewMonth] = useState(selectedDate.getMonth());

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
      <View style={styles.overlay}>
        <View style={styles.container}>
          <Text style={styles.title}>{title}</Text>

          <View style={styles.monthNav}>
            <TouchableOpacity onPress={prevMonth} style={styles.navBtn}>
              <MaterialIcons name="chevron-left" size={24} color={C.foreground} />
            </TouchableOpacity>
            <Text style={styles.monthLabel}>{MONTHS_RU[viewMonth]} {viewYear}</Text>
            <TouchableOpacity onPress={nextMonth} style={styles.navBtn}>
              <MaterialIcons name="chevron-right" size={24} color={C.foreground} />
            </TouchableOpacity>
          </View>

          <View style={styles.daysRow}>
            {DAYS_RU.map((d) => (
              <Text key={d} style={styles.dayHeader}>{d}</Text>
            ))}
          </View>

          <View style={styles.grid}>
            {days.map((d, i) => (
              <TouchableOpacity
                key={i}
                style={[
                  styles.dayCell,
                  d !== null && isSelected(d) && styles.dayCellSelected,
                  d !== null && isToday(d) && !isSelected(d) && styles.dayCellToday,
                ]}
                onPress={() => { if (d !== null) setCurrent(new Date(viewYear, viewMonth, d)); }}
                disabled={d === null}
              >
                {d !== null && (
                  <Text style={[
                    styles.dayText,
                    isSelected(d) && styles.dayTextSelected,
                    isToday(d) && !isSelected(d) && styles.dayTextToday,
                  ]}>
                    {d}
                  </Text>
                )}
              </TouchableOpacity>
            ))}
          </View>

          <View style={styles.actions}>
            <TouchableOpacity style={styles.cancelBtn} onPress={onDismiss}>
              <Text style={styles.cancelText}>Отмена</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.confirmBtn} onPress={() => onConfirm(current)}>
              <Text style={styles.confirmText}>Выбрать</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.75)',
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
    width: `${100 / 7}%` as any,
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
