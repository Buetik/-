import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import { SymbolWeight, SymbolViewProps } from 'expo-symbols';
import { ComponentProps } from 'react';
import { OpaqueColorValue, type StyleProp, type TextStyle } from 'react-native';

type IconMapping = Record<string, ComponentProps<typeof MaterialIcons>['name']>;
type IconSymbolName = keyof typeof MAPPING | string;

const MAPPING = {
  // Navigation
  'house.fill': 'home',
  'grid.fill': 'grid-view',
  'chart.bar.doc.horizontal.fill': 'bar-chart',
  // Actions
  'plus': 'add',
  'plus.circle.fill': 'add-circle',
  'arrow.left': 'arrow-back',
  'chevron.left': 'chevron-left',
  'chevron.right': 'chevron-right',
  'chevron.down': 'expand-more',
  'xmark': 'close',
  'xmark.circle.fill': 'cancel',
  // Content
  'calendar': 'calendar-today',
  'camera.fill': 'photo-camera',
  'photo.fill': 'image',
  'doc.text.fill': 'description',
  'square.and.arrow.up': 'ios-share',
  'doc.on.clipboard': 'content-copy',
  'checkmark.circle.fill': 'check-circle',
  'exclamationmark.triangle.fill': 'warning',
  'trash.fill': 'delete',
  // Misc
  'paperplane.fill': 'send',
  'chevron.left.forwardslash.chevron.right': 'code',
} as IconMapping;

export function IconSymbol({
  name,
  size = 24,
  color,
  style,
}: {
  name: IconSymbolName;
  size?: number;
  color: string | OpaqueColorValue;
  style?: StyleProp<TextStyle>;
  weight?: SymbolWeight;
}) {
  // Safely resolve icon name with robust fallback
  let mappedName: any = MAPPING[name as string];
  
  // Ensure we always have a valid, non-empty string
  if (!mappedName || typeof mappedName !== 'string' || mappedName.trim().length === 0) {
    mappedName = 'help-outline';
  }
  
  // Additional safety: ensure size is a positive number
  const safeSize = typeof size === 'number' && size > 0 ? size : 24;
  
  try {
    return <MaterialIcons color={color} size={safeSize} name={mappedName} style={style} />;
  } catch (e) {
    // Fallback to help icon if rendering fails
    return <MaterialIcons color={color} size={safeSize} name="help-outline" style={style} />;
  }
}
