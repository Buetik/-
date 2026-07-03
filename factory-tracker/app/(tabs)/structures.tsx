import React, { useState, useCallback, useEffect } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Modal,
  TextInput,
  Image,
  Alert,
  ActivityIndicator,
  Dimensions,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  AppState,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import * as ImagePicker from 'expo-image-picker';
import { useData, Structure } from '@/lib/data-context';

const C = {
  bg: '#1E252B',
  surface: '#2A333C',
  primary: '#FF6B00',
  foreground: '#FFFFFF',
  muted: '#A0AAB2',
  border: '#3A4550',
  error: '#F87171',
  overlay: 'rgba(0,0,0,0.7)',
};

const SCREEN_WIDTH = Dimensions.get('window').width;
const CARD_SIZE = (SCREEN_WIDTH - 16 * 2 - 12) / 2;

function StructureCard({ item }: { item: Structure }) {
  return (
    <View style={styles.card}>
      {item.photoUri ? (
        <Image
          source={{ uri: item.photoUri }}
          style={styles.cardImage}
          resizeMode="cover"
        />
      ) : (
        <View style={styles.cardImagePlaceholder}>
          <MaterialIcons name="factory" size={40} color={C.primary} />
        </View>
      )}
      <View style={styles.cardFooter}>
        <Text style={styles.cardName} numberOfLines={2}>{item.name}</Text>
      </View>
    </View>
  );
}

interface AddStructureModalProps {
  visible: boolean;
  onClose: () => void;
  onSave: (name: string, photoUri: string) => void;
}

function AddStructureModal({ visible, onClose, onSave }: AddStructureModalProps) {
  const [name, setName] = useState('');
  const [photoUri, setPhotoUri] = useState('');
  const [nameError, setNameError] = useState('');
  const [photoError, setPhotoError] = useState('');
  const [saving, setSaving] = useState(false);
  const [permissionStatus, setPermissionStatus] = useState<string | null>(null);

  const reset = useCallback(() => {
    setName('');
    setPhotoUri('');
    setNameError('');
    setPhotoError('');
    setSaving(false);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  // Check and request permissions when modal opens
  useEffect(() => {
    if (visible) {
      checkMediaLibraryPermissions();
    }
  }, [visible]);

  // Handle app state changes to get pending results
  useEffect(() => {
    const subscription = AppState.addEventListener('change', handleAppStateChange);
    return () => subscription.remove();
  }, []);

  const handleAppStateChange = async (nextAppState: string) => {
    if (nextAppState === 'active') {
      try {
        const result = await ImagePicker.getPendingResultAsync();
        if (result && typeof result === 'object' && !Array.isArray(result)) {
          const pickerResult = result as any;
          if (pickerResult.canceled === false && pickerResult.assets && pickerResult.assets.length > 0) {
            setPhotoUri(pickerResult.assets[0].uri);
            setPhotoError('');
          }
        }
      } catch (error) {
        console.error('Error getting pending result:', error);
      }
    }
  };

  const checkMediaLibraryPermissions = async () => {
    try {
      const { status } = await ImagePicker.getMediaLibraryPermissionsAsync();
      setPermissionStatus(status);

      if (status !== 'granted' && status !== 'undetermined') {
        setPhotoError('Требуется доступ к галерее');
      }
    } catch (error) {
      console.error('Error checking permissions:', error);
    }
  };

  const handlePickPhoto = useCallback(async () => {
    try {
      // Request permission if needed
      const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (status !== 'granted') {
        setPhotoError('Доступ к галерее запрещен');
        return;
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.8,
      });

      if (!result.canceled && result.assets.length > 0) {
        setPhotoUri(result.assets[0].uri);
        setPhotoError('');
      }
    } catch (error) {
      console.error('Error picking image:', error);
      setPhotoError('Ошибка при выборе фото');
    }
  }, []);

  const handleSave = useCallback(async () => {
    let valid = true;
    if (!name.trim()) {
      setNameError('Обязательное поле');
      valid = false;
    } else if (name.trim().length < 2) {
      setNameError('Минимум 2 символа');
      valid = false;
    } else {
      setNameError('');
    }

    if (!valid) return;

    setSaving(true);
    try {
      onSave(name.trim(), photoUri);
      reset();
      onClose();
    } finally {
      setSaving(false);
    }
  }, [name, photoUri, onSave, reset, onClose]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={handleClose}>
      <KeyboardAvoidingView
        style={styles.modalOverlay}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <View style={styles.modalSheet}>
          {/* Header */}
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Добавить конструкцию</Text>
            <TouchableOpacity onPress={handleClose} style={styles.modalCloseBtn}>
              <MaterialIcons name="close" size={24} color={C.muted} />
            </TouchableOpacity>
          </View>

          <ScrollView showsVerticalScrollIndicator={false}>
            {/* Name Field */}
            <View style={styles.fieldGroup}>
              <Text style={styles.fieldLabel}>Название конструкции</Text>
              <TextInput
                style={[styles.textInput, nameError ? styles.textInputError : null]}
                placeholder="Например: Конструкция А1"
                placeholderTextColor={C.muted}
                value={name}
                onChangeText={(t) => { setName(t); if (t.trim()) setNameError(''); }}
                returnKeyType="done"
                maxLength={100}
                autoFocus
              />
              {nameError ? <Text style={styles.errorText}>{nameError}</Text> : null}
            </View>

            {/* Photo Picker */}
            <View style={styles.fieldGroup}>
              <Text style={styles.fieldLabel}>Фото конструкции (опционально)</Text>
              <TouchableOpacity style={styles.photoPickerBtn} onPress={handlePickPhoto} activeOpacity={0.8}>
                <MaterialIcons name="photo-camera" size={20} color={C.primary} />
                <Text style={styles.photoPickerText}>Выбрать фото из галереи</Text>
              </TouchableOpacity>
              {photoUri ? (
                <View style={styles.photoPreviewContainer}>
                  <Image source={{ uri: photoUri }} style={styles.photoPreview} resizeMode="cover" />
                  <TouchableOpacity
                    style={styles.photoRemoveBtn}
                    onPress={() => setPhotoUri('')}
                  >
                    <MaterialIcons name="cancel" size={22} color={C.error} />
                  </TouchableOpacity>
                </View>
              ) : null}
              {photoError ? <Text style={styles.errorText}>{photoError}</Text> : null}
            </View>

            {/* Info */}
            <View style={styles.infoBox}>
              <MaterialIcons name="info" size={20} color={C.primary} />
              <Text style={styles.infoText}>Фото используется для визуальной идентификации конструкции</Text>
            </View>

            {/* Save Button */}
            <TouchableOpacity
              style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
              onPress={handleSave}
              activeOpacity={0.85}
              disabled={saving}
            >
              {saving ? (
                <ActivityIndicator color="#FFFFFF" size="small" />
              ) : (
                <Text style={styles.saveBtnText}>Добавить</Text>
              )}
            </TouchableOpacity>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export default function StructuresScreen() {
  const { state, addStructure } = useData();
  const [modalVisible, setModalVisible] = useState(false);

  const handleSave = useCallback(
    async (name: string, photoUri: string) => {
      await addStructure(name, photoUri);
    },
    [addStructure]
  );

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      {/* Top App Bar */}
      <View style={styles.appBar}>
        <Text style={styles.appBarTitle}>Справочник конструкций</Text>
        <Text style={styles.appBarCount}>{state.structures.length} шт.</Text>
      </View>

      <FlatList
        data={state.structures}
        keyExtractor={(item) => item.id}
        numColumns={2}
        contentContainerStyle={styles.gridContent}
        columnWrapperStyle={styles.gridRow}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <MaterialIcons name="grid-view" size={56} color={C.muted} />
            <Text style={styles.emptyTitle}>Конструкции еще не добавлены</Text>
            <Text style={styles.emptySubtitle}>Нажмите + чтобы добавить первую конструкцию</Text>
          </View>
        }
        renderItem={({ item }) => <StructureCard item={item} />}
        showsVerticalScrollIndicator={false}
      />

      {/* FAB */}
      <TouchableOpacity
        style={styles.fab}
        onPress={() => setModalVisible(true)}
        activeOpacity={0.85}
      >
        <MaterialIcons name="add" size={28} color="#FFFFFF" />
      </TouchableOpacity>

      <AddStructureModal
        visible={modalVisible}
        onClose={() => setModalVisible(false)}
        onSave={handleSave}
      />
    </SafeAreaView>
  );
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
    fontSize: 18,
    fontWeight: '700',
    color: C.foreground,
    flex: 1,
  },
  appBarCount: {
    fontSize: 13,
    color: C.muted,
    fontWeight: '500',
  },
  gridContent: {
    padding: 16,
    paddingBottom: 100,
    flexGrow: 1,
  },
  gridRow: {
    gap: 12,
    marginBottom: 12,
  },
  card: {
    width: CARD_SIZE,
    backgroundColor: C.surface,
    borderRadius: 14,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: C.border,
  },
  cardImage: {
    width: '100%',
    height: CARD_SIZE,
  },
  cardImagePlaceholder: {
    width: '100%',
    height: CARD_SIZE,
    backgroundColor: '#1A2028',
    alignItems: 'center',
    justifyContent: 'center',
  },
  cardFooter: {
    padding: 10,
  },
  cardName: {
    fontSize: 13,
    fontWeight: '600',
    color: C.foreground,
    lineHeight: 18,
  },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 80,
    gap: 10,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: C.muted,
    textAlign: 'center',
  },
  emptySubtitle: {
    fontSize: 13,
    color: C.muted,
    textAlign: 'center',
    opacity: 0.7,
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
  // Modal
  modalOverlay: {
    flex: 1,
    backgroundColor: C.overlay,
    justifyContent: 'flex-end',
  },
  modalSheet: {
    backgroundColor: C.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 20,
    paddingBottom: 32,
    paddingTop: 20,
    maxHeight: '90%',
    borderTopWidth: 1,
    borderTopColor: C.border,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 20,
  },
  modalTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: C.foreground,
    flex: 1,
  },
  modalCloseBtn: {
    padding: 4,
  },
  fieldGroup: {
    marginBottom: 16,
  },
  fieldLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: C.muted,
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  textInput: {
    backgroundColor: '#1A2028',
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: C.foreground,
  },
  textInputError: {
    borderColor: C.error,
  },
  errorText: {
    fontSize: 12,
    color: C.error,
    marginTop: 5,
  },
  photoPickerBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#1A2028',
    borderWidth: 1,
    borderColor: C.primary,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderStyle: 'dashed',
  },
  photoPickerText: {
    fontSize: 15,
    color: C.primary,
    fontWeight: '600',
  },
  photoPreviewContainer: {
    marginTop: 10,
    position: 'relative',
    alignSelf: 'flex-start',
  },
  photoPreview: {
    width: 80,
    height: 80,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: C.border,
  },
  photoRemoveBtn: {
    position: 'absolute',
    top: -8,
    right: -8,
    backgroundColor: C.surface,
    borderRadius: 12,
  },
  infoBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    backgroundColor: '#1A2028',
    borderWidth: 1,
    borderColor: C.primary,
    borderRadius: 10,
    padding: 12,
    marginBottom: 20,
  },
  infoText: {
    fontSize: 13,
    color: C.muted,
    flex: 1,
    lineHeight: 18,
  },
  saveBtn: {
    backgroundColor: C.primary,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 8,
  },
  saveBtnDisabled: {
    opacity: 0.6,
  },
  saveBtnText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#FFFFFF',
    letterSpacing: 0.3,
  },
});
