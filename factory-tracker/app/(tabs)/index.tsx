import React, { useMemo } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  Pressable,
  TouchableOpacity,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import { useData, formatDate, formatTime, startOfDay, endOfDay, ProductionReport } from '@/lib/data-context';

const C = {
  bg: '#1E252B',
  surface: '#2A333C',
  primary: '#FF6B00',
  foreground: '#FFFFFF',
  muted: '#A0AAB2',
  border: '#3A4550',
  success: '#4ADE80',
};

function getTodayRange() {
  const now = Date.now();
  return { start: startOfDay(now), end: endOfDay(now) };
}

function ReportRow({ item }: { item: ProductionReport }) {
  return (
    <View style={styles.reportRow}>
      <View style={styles.reportRowLeft}>
        <Text style={styles.reportName} numberOfLines={1}>{item.structureName}</Text>
        <Text style={styles.reportTime}>{formatTime(item.date)}</Text>
      </View>
      <View style={styles.quantityBadge}>
        <Text style={styles.quantityText}>{item.quantity} шт.</Text>
      </View>
    </View>
  );
}

export default function DashboardScreen() {
  const router = useRouter();
  const { state } = useData();

  const today = useMemo(() => getTodayRange(), []);
  const todayDate = useMemo(() => formatDate(Date.now()), []);

  const todayReports = useMemo(
    () =>
      state.reports
        .filter((r) => r.date >= today.start && r.date <= today.end)
        .sort((a, b) => b.date - a.date),
    [state.reports, today]
  );

  const todayTotal = useMemo(
    () => todayReports.reduce((sum, r) => sum + r.quantity, 0),
    [todayReports]
  );

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      {/* Top App Bar */}
      <View style={styles.appBar}>
        <Text style={styles.appBarTitle}>Главная</Text>
        <Text style={styles.appBarDate}>{todayDate}</Text>
      </View>

      <FlatList
        data={todayReports}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.listContent}
        ListHeaderComponent={
          <>
            {/* Summary Card */}
            <View style={styles.summaryCard}>
              <Text style={styles.summaryLabel}>Итого за сегодня</Text>
              <View style={styles.summaryRow}>
                <MaterialIcons name="inventory" size={32} color={C.primary} />
                <Text style={styles.summaryValue}>{todayTotal} шт.</Text>
              </View>
              <Text style={styles.summarySubtitle}>{todayReports.length} {getReportWord(todayReports.length)}</Text>
            </View>

            {/* Section Header */}
            <Text style={styles.sectionHeader}>Записи за сегодня</Text>
          </>
        }
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <MaterialIcons name="inbox" size={48} color={C.muted} />
            <Text style={styles.emptyText}>Сегодня отчетов еще не было</Text>
          </View>
        }
        renderItem={({ item }) => <ReportRow item={item} />}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        showsVerticalScrollIndicator={false}
      />

      {/* FAB */}
      <TouchableOpacity
        style={styles.fab}
        onPress={() => router.push('/new-report' as any)}
        activeOpacity={0.85}
      >
        <MaterialIcons name="add" size={28} color="#FFFFFF" />
      </TouchableOpacity>
    </SafeAreaView>
  );
}

function getReportWord(count: number): string {
  if (count === 1) return 'запись';
  if (count >= 2 && count <= 4) return 'записи';
  return 'записей';
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: C.bg,
  },
  appBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 14,
    backgroundColor: C.surface,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  appBarTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: C.foreground,
    letterSpacing: 0.3,
  },
  appBarDate: {
    fontSize: 14,
    color: C.muted,
    fontWeight: '500',
  },
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 100,
    flexGrow: 1,
  },
  summaryCard: {
    backgroundColor: C.surface,
    borderRadius: 16,
    padding: 20,
    marginTop: 16,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: C.border,
    borderLeftWidth: 4,
    borderLeftColor: C.primary,
  },
  summaryLabel: {
    fontSize: 13,
    color: C.muted,
    fontWeight: '500',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 10,
  },
  summaryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginBottom: 6,
  },
  summaryValue: {
    fontSize: 40,
    fontWeight: '800',
    color: C.foreground,
    letterSpacing: -1,
  },
  summarySubtitle: {
    fontSize: 13,
    color: C.muted,
  },
  sectionHeader: {
    fontSize: 14,
    fontWeight: '700',
    color: C.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginTop: 20,
    marginBottom: 10,
  },
  reportRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: C.surface,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: C.border,
  },
  reportRowLeft: {
    flex: 1,
    marginRight: 12,
  },
  reportName: {
    fontSize: 15,
    fontWeight: '600',
    color: C.foreground,
    marginBottom: 3,
  },
  reportTime: {
    fontSize: 12,
    color: C.muted,
  },
  quantityBadge: {
    backgroundColor: '#FF6B0020',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: '#FF6B0050',
  },
  quantityText: {
    fontSize: 14,
    fontWeight: '700',
    color: C.primary,
  },
  separator: {
    height: 8,
  },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
    gap: 12,
  },
  emptyText: {
    fontSize: 15,
    color: C.muted,
    textAlign: 'center',
  },
  fab: {
    position: 'absolute',
    right: 20,
    bottom: 90,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: C.primary,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 8,
    shadowColor: C.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
  },
});
