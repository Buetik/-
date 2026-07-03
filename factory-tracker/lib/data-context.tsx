import React, { createContext, useContext, useReducer, useEffect, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Structure {
  id: string;
  name: string;
  photoUri: string;
}

export interface ProductionReport {
  id: string;
  date: number; // timestamp ms
  structureId: string;
  structureName: string;
  quantity: number;
}

interface DataState {
  structures: Structure[];
  reports: ProductionReport[];
  loaded: boolean;
}

type DataAction =
  | { type: 'LOAD'; payload: { structures: Structure[]; reports: ProductionReport[] } }
  | { type: 'ADD_STRUCTURE'; payload: Structure }
  | { type: 'DELETE_STRUCTURE'; payload: string }
  | { type: 'ADD_REPORT'; payload: ProductionReport }
  | { type: 'DELETE_REPORT'; payload: string };

// ─── Reducer ──────────────────────────────────────────────────────────────────

function dataReducer(state: DataState, action: DataAction): DataState {
  switch (action.type) {
    case 'LOAD':
      return { ...state, structures: action.payload.structures, reports: action.payload.reports, loaded: true };
    case 'ADD_STRUCTURE':
      return { ...state, structures: [...state.structures, action.payload] };
    case 'DELETE_STRUCTURE':
      return { ...state, structures: state.structures.filter((s) => s.id !== action.payload) };
    case 'ADD_REPORT':
      return { ...state, reports: [...state.reports, action.payload] };
    case 'DELETE_REPORT':
      return { ...state, reports: state.reports.filter((r) => r.id !== action.payload) };
    default:
      return state;
  }
}

// ─── Context ──────────────────────────────────────────────────────────────────

const STRUCTURES_KEY = '@factory_tracker_structures';
const REPORTS_KEY = '@factory_tracker_reports';

interface DataContextValue {
  state: DataState;
  addStructure: (name: string, photoUri: string) => Promise<void>;
  deleteStructure: (id: string) => Promise<void>;
  addReport: (date: number, structureId: string, structureName: string, quantity: number) => Promise<void>;
  deleteReport: (id: string) => Promise<void>;
}

const DataContext = createContext<DataContextValue | null>(null);

export function DataProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(dataReducer, {
    structures: [],
    reports: [],
    loaded: false,
  });

  // Load from AsyncStorage on mount
  useEffect(() => {
    (async () => {
      try {
        const [structuresJson, reportsJson] = await Promise.all([
          AsyncStorage.getItem(STRUCTURES_KEY),
          AsyncStorage.getItem(REPORTS_KEY),
        ]);
        dispatch({
          type: 'LOAD',
          payload: {
            structures: structuresJson ? JSON.parse(structuresJson) : [],
            reports: reportsJson ? JSON.parse(reportsJson) : [],
          },
        });
      } catch (error) {
        console.error('Failed to load data from AsyncStorage:', error);
        dispatch({ type: 'LOAD', payload: { structures: [], reports: [] } });
      }
    })();
  }, []);

  // Persist structures whenever they change
  useEffect(() => {
    if (!state.loaded) return;
    AsyncStorage.setItem(STRUCTURES_KEY, JSON.stringify(state.structures)).catch((error) => {
      console.error('Failed to save structures:', error);
    });
  }, [state.structures, state.loaded]);

  // Persist reports whenever they change
  useEffect(() => {
    if (!state.loaded) return;
    AsyncStorage.setItem(REPORTS_KEY, JSON.stringify(state.reports)).catch((error) => {
      console.error('Failed to save reports:', error);
    });
  }, [state.reports, state.loaded]);

  const addStructure = useCallback(async (name: string, photoUri: string) => {
    const id = `s_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    dispatch({ type: 'ADD_STRUCTURE', payload: { id, name, photoUri } });
  }, []);

  const deleteStructure = useCallback(async (id: string) => {
    dispatch({ type: 'DELETE_STRUCTURE', payload: id });
  }, []);

  const addReport = useCallback(
    async (date: number, structureId: string, structureName: string, quantity: number) => {
      const id = `r_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      dispatch({ type: 'ADD_REPORT', payload: { id, date, structureId, structureName, quantity } });
    },
    []
  );

  const deleteReport = useCallback(async (id: string) => {
    dispatch({ type: 'DELETE_REPORT', payload: id });
  }, []);

  return (
    <DataContext.Provider value={{ state, addStructure, deleteStructure, addReport, deleteReport }}>
      {children}
    </DataContext.Provider>
  );
}

export function useData(): DataContextValue {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error('useData must be used within DataProvider');
  return ctx;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function formatDate(timestamp: number): string {
  const d = new Date(timestamp);
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = d.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

export function startOfDay(date: Date | number): number {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function endOfDay(date: Date | number): number {
  const d = new Date(date);
  d.setHours(23, 59, 59, 999);
  return d.getTime();
}

export function formatTime(timestamp: number): string {
  const d = new Date(timestamp);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}
