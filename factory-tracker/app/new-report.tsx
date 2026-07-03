import React, { useState, useCallback, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  Modal,
  FlatList,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ToastAndroid,
  Alert,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import { useData, formatDate } from '@/lib/data-context';

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

// Simple date picker using modal with calendar-like grid
interface DatePickerModalProps {
  visible: boolean;
  selectedDate: Date;
  onConfirm: (date: Date) => void;
  onDismiss: () => void;
}

function DatePickerModal({ visible, selectedDate, onConfirm, onDismiss }: DatePickerModalProps) {
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
    const startDow = (firstDay.getDay() + 6) % 7; // Mon=0
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
          <Text style={dpStyles.title}>Выберите дату</Text>

          {/* Month navigation */}
          <View style={dpStyles.monthNav}>
            <TouchableOpacity onPress={prevMonth} style={dpStyles.navBtn}>
              <MaterialIcons name="chevron-left" size={24} color={C.foreground} />
            </TouchableOpacity>
            <Text style={dpStyles.monthLabel}>{MONTHS_RU[viewMonth]} {viewYear}</Text>
            <TouchableOpacity onPress={nextMonth} style={dpStyles.navBtn}>
              <MaterialIcons name="chevron-right" size={24} color={C.foreground} />
            </TouchableOpacity>
          </View>

          {/* Day headers */}
          <View style={dpStyles.daysRow}>
            {DAYS_RU.map((d) => (
              <Text key={d} style={dpStyles.dayHeader}>{d}</Text>
            ))}
          </View>

          {/* Calendar grid */}
          <View style={dpStyles.grid}>
            {days.map((d, i) => (
              <TouchableOpacity
                key={i}
                style={[
                  dpStyles.dayCell,
                  d !== null && isSelected(d) && dpStyles.dayCellSelected,
                  d !== null && isToday(d) && !isSelected(d) && dpStyles.dayCellToday,
                ]}
                onPress={() => {
                  if (d !== null) {
                    const nd = new Date(viewYear, viewMonth, d);
                    setCurrent(nd);
                  }
                }}
                disabled={d === null}
              >
                {d !== null && (
                  <Text
                    style={[
                      dpStyles.dayText,
                      isSelected(d) && dpStyles.dayTextSelected,
                      isToday(d) && !isSelected(d) && dpStyles.dayTextToday,
                    ]}
                  >
                    {d}
                  </Text>
                )}
              </TouchableOpacity>
            ))}
          </View>

          {/* Actions */}
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

// Structure dropdown modal
interface StructurePickerModalProps {
  visible: boolean;
  structures: { id: string; name: string }[];
  selectedId: string;
  onSelect: (id: string, name: string) => void;
  onDismiss: () => void;
}

function StructurePickerModal({ visible, structures, selectedId, onSelect, onDismiss }: StructurePickerModalProps) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onDismiss}>
      <View style={spStyles.overlay}>
        <View style={spStyles.sheet}>
          <View style={spStyles.header}>
            <Text style={spStyles.title}>Выберите конструкцию</Text>
            <TouchableOpacity onPress={onDismiss}>
              <MaterialIcons name="close" size={24} color={C.muted} />
            </TouchableOpacity>
          </View>
          {structures.length === 0 ? (
            <View style={spStyles.empty}>
              <Text style={spStyles.emptyText}>Сначала добавьте конструкции в справочник</Text>
            </View>
          ) : (
            <FlatList
              data={structures}
              keyExtractor={(item) => item.id}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={[spStyles.item, item.id === selectedId && spStyles.itemSelected]}
                  onPress={() => { onSelect(item.id, item.name); onDismiss(); }}
                >
                  <Text style={[spStyles.itemText, item.id === selectedId && spStyles.itemTextSelected]}>
                    {item.name}
                  </Text>
                  {item.id === selectedId && (
                    <MaterialIcons name="check-circle" size={20} color={C.primary} />
                  )}
                </TouchableOpacity>
              )}
              ItemSeparatorComponent={() => <View style={spStyles.separator} />}
            />
          )}
        </View>
      </View>
    </Modal>
  );
}

export default function NewReportScreen() {
  const router = useRouter();
  const { state, addReport } = useData();

  const [selectedDate, setSelectedDate] = useState(new Date());
  const [structureId, setStructureId] = useState('');
  const [structureName, setStructureName] = useState('');
  const [quantity, setQuantity] = useState('');
  const [saving, setSaving] = useState(false);

  const [datePickerVisible, setDatePickerVisible] = useState(false);
  const [structurePickerVisible, setStructurePickerVisible] = useState(false);

  const [structureError, setStructureError] = useState('');
  const [quantityError, setQuantityError] = useState('');

  const handleSave = useCallback(async () => {
    let valid = true;

    if (!structureId) {
      setStructureError('Обязательное поле');
      valid = false;
    } else {
      setStructureError('');
    }

    const qty = parseInt(quantity, 10);
    if (!quantity.trim() || isNaN(qty) || qty <= 0) {
      setQuantityError('Введите корректное число больше 0');
      valid = false;
    } else {
      setQuantityError('');
    }

    if (!valid) return;

    setSaving(true);
    try {
      // Set time to current time but keep selected date
      const reportDate = new Date(selectedDate);
      const now = new Date();
      reportDate.setHours(now.getHours(), now.getMinutes(), now.getSeconds(), now.getMilliseconds());

      await addReport(reportDate.getTime(), structureId, structureName, qty);
      showToast('Отчет успешно сохранен');
      router.back();
    } finally {
      setSaving(false);
    }
  }, [structureId, structureName, quantity, selectedDate, addReport, router]);

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      {/* Top App Bar */}
      <View style={styles.appBar}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
          <MaterialIcons name="arrow-back" size={24} color={C.foreground} />
        </TouchableOpacity>
        <Text style={styles.appBarTitle}>Добавить отчет</Text>
        <View style={styles.backBtn} />
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          {/* Date Field */}
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Дата</Text>
            <TouchableOpacity
              style={styles.selectField}
              onPress={() => setDatePickerVisible(true)}
              activeOpacity={0.8}
            >
              <MaterialIcons name="calendar-today" size={18} color={C.primary} />
              <Text style={styles.selectFieldText}>{formatDate(selectedDate.getTime())}</Text>
              <MaterialIcons name="expand-more" size={20} color={C.muted} />
            </TouchableOpacity>
          </View>

          {/* Structure Dropdown */}
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Конструкция</Text>
            <TouchableOpacity
              style={[styles.selectField, structureError ? styles.selectFieldError : null]}
              onPress={() => setStructurePickerVisible(true)}
              activeOpacity={0.8}
            >
              <MaterialIcons name="grid-view" size={18} color={structureId ? C.primary : C.muted} />
              <Text style={[styles.selectFieldText, !structureId && styles.selectFieldPlaceholder]}>
                {structureName || 'Выберите конструкцию'}
              </Text>
              <MaterialIcons name="expand-more" size={20} color={C.muted} />
            </TouchableOpacity>
            {structureError ? <Text style={styles.errorText}>{structureError}</Text> : null}
          </View>

          {/* Quantity Field */}
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Количество (шт.)</Text>
            <TextInput
              style={[styles.textInput, quantityError ? styles.textInputError : null]}
              placeholder="Количество (шт.)"
              placeholderTextColor={C.muted}
              value={quantity}
              onChangeText={(t) => {
                setQuantity(t.replace(/[^0-9]/g, ''));
                if (t.trim()) setQuantityError('');
              }}
              keyboardType="number-pad"
              returnKeyType="done"
              maxLength={6}
            />
            {quantityError ? <Text style={styles.errorText}>{quantityError}</Text> : null}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>

      {/* Save Button */}
      <View style={styles.footer}>
        <TouchableOpacity
          style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
          onPress={handleSave}
          activeOpacity={0.85}
          disabled={saving}
        >
          {saving ? (
            <ActivityIndicator color="#FFFFFF" size="small" />
          ) : (
            <>
              <MaterialIcons name="check-circle" size={20} color="#FFFFFF" />
              <Text style={styles.saveBtnText}>Сохранить отчет</Text>
            </>
          )}
        </TouchableOpacity>
      </View>

      <DatePickerModal
        visible={datePickerVisible}
        selectedDate={selectedDate}
        onConfirm={(date) => { setSelectedDate(date); setDatePickerVisible(false); }}
        onDismiss={() => setDatePickerVisible(false)}
      />

      <StructurePickerModal
        visible={structurePickerVisible}
        structures={state.structures}
        selectedId={structureId}
        onSelect={(id, name) => {
          setStructureId(id);
          setStructureName(name);
          setStructureError('');
        }}
        onDismiss={() => setStructurePickerVisible(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  appBar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 12,
    backgroundColor: C.surface,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  backBtn: { width: 40, alignItems: 'center' },
  appBarTitle: {
    flex: 1,
    fontSize: 18,
    fontWeight: '700',
    color: C.foreground,
    textAlign: 'center',
  },
  content: {
    padding: 20,
    paddingBottom: 20,
  },
  fieldGroup: { marginBottom: 20 },
  fieldLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: C.muted,
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  selectField: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#1A2028',
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 14,
  },
  selectFieldError: { borderColor: C.error },
  selectFieldText: {
    flex: 1,
    fontSize: 15,
    color: C.foreground,
    fontWeight: '500',
  },
  selectFieldPlaceholder: { color: C.muted, fontWeight: '400' },
  textInput: {
    backgroundColor: '#1A2028',
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 14,
    fontSize: 15,
    color: C.foreground,
  },
  textInputError: { borderColor: C.error },
  errorText: { fontSize: 12, color: C.error, marginTop: 5 },
  footer: {
    paddingHorizontal: 20,
    paddingVertical: 16,
    paddingBottom: Platform.OS === 'ios' ? 24 : 16,
    backgroundColor: C.bg,
    borderTopWidth: 1,
    borderTopColor: C.border,
  },
  saveBtn: {
    backgroundColor: C.primary,
    borderRadius: 12,
    paddingVertical: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  saveBtnDisabled: { opacity: 0.6 },
  saveBtnText: { fontSize: 16, fontWeight: '700', color: '#FFFFFF', letterSpacing: 0.3 },
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
  daysRow: {
    flexDirection: 'row',
    marginBottom: 6,
  },
  dayHeader: {
    flex: 1,
    textAlign: 'center',
    fontSize: 12,
    fontWeight: '600',
    color: C.muted,
    paddingVertical: 4,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
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
  actions: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 16,
  },
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

const spStyles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: C.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 20,
    paddingBottom: 32,
    paddingTop: 20,
    maxHeight: '70%',
    borderTopWidth: 1,
    borderTopColor: C.border,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  title: { fontSize: 17, fontWeight: '700', color: C.foreground },
  empty: { paddingVertical: 40, alignItems: 'center' },
  emptyText: { fontSize: 14, color: C.muted, textAlign: 'center' },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    paddingHorizontal: 12,
    borderRadius: 10,
  },
  itemSelected: { backgroundColor: '#FF6B0015' },
  itemText: { fontSize: 15, color: C.foreground, flex: 1 },
  itemTextSelected: { color: C.primary, fontWeight: '600' },
  separator: { height: 1, backgroundColor: C.border },
});
