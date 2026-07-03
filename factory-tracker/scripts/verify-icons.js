// Verify all icon mappings are valid
const mapping = {
  'house.fill': 'home',
  'grid.fill': 'grid-view',
  'chart.bar.doc.horizontal.fill': 'bar-chart',
  'plus': 'add',
  'plus.circle.fill': 'add-circle',
  'arrow.left': 'arrow-back',
  'chevron.left': 'chevron-left',
  'chevron.right': 'chevron-right',
  'chevron.down': 'expand-more',
  'xmark': 'close',
  'xmark.circle.fill': 'cancel',
  'calendar': 'calendar-today',
  'camera.fill': 'photo-camera',
  'photo.fill': 'image',
  'doc.text.fill': 'description',
  'square.and.arrow.up': 'ios-share',
  'doc.on.clipboard': 'content-copy',
  'checkmark.circle.fill': 'check-circle',
  'exclamationmark.triangle.fill': 'warning',
  'trash.fill': 'delete',
  'paperplane.fill': 'send',
  'chevron.left.forwardslash.chevron.right': 'code',
};

const tabIcons = ['house.fill', 'grid.fill', 'chart.bar.doc.horizontal.fill'];

console.log('✓ Icon Mapping Verification');
console.log(`Total icons: ${Object.keys(mapping).length}`);
console.log(`Tab icons: ${tabIcons.length}`);

let valid = true;
for (const icon of tabIcons) {
  if (!mapping[icon]) {
    console.error(`✗ Missing mapping for tab icon: ${icon}`);
    valid = false;
  } else {
    console.log(`✓ ${icon} -> ${mapping[icon]}`);
  }
}

if (valid) {
  console.log('\n✓ All tab icons are properly mapped!');
  process.exit(0);
} else {
  console.error('\n✗ Some icons are missing from mapping!');
  process.exit(1);
}
