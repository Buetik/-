import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import { ComponentProps } from 'react';
import { OpaqueColorValue, type StyleProp, type TextStyle } from 'react-native';

type IconMapping = Record<string, ComponentProps<typeof MaterialIcons>['name']>;

const MAPPING: IconMapping = {
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
};

export function IconSymbol({
  name,
  size = 24,
  color,
  style,
}: {
  name: string;
  size?: number;
  color: string | OpaqueColorValue;
  style?: StyleProp<TextStyle>;
  weight?: any;
}) {
  // Safely resolve icon name with robust fallback
  let mappedName: any = MAPPING[name as string];
  
  // Ensure we always have a valid string
  if (!mappedName || typeof mappedName !== 'string' || mappedName.length === 0) {
    mappedName = 'help-outline';
  }
  
  try {
    return <MaterialIcons color={color} size={size} name={mappedName} style={style} />;
  } catch (e) {
    // Fallback to help icon if rendering fails
    return <MaterialIcons color={color} size={size} name="help-outline" style={style} />;
  }
}
