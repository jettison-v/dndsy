import re

def is_mobile(user_agent_string):
    """
    Determines if the request is from a mobile device based on the user agent string.
    
    Args:
        user_agent_string (str): The User-Agent header from the request
        
    Returns:
        bool: True if the request is from a mobile device, False otherwise
    """
    if not user_agent_string:
        return False
        
    # Common mobile device patterns
    mobile_patterns = [
        r'Android.*Mobile',
        r'iPhone',
        r'iPad',
        r'iPod',
        r'BlackBerry',
        r'IEMobile',
        r'Opera Mini',
        r'webOS',
        r'Mobile Safari'
    ]
    
    # Check if any mobile patterns match
    return any(re.search(pattern, user_agent_string) for pattern in mobile_patterns)

def is_tablet(user_agent_string):
    """
    Determines if the request is from a tablet device.
    
    Args:
        user_agent_string (str): The User-Agent header from the request
        
    Returns:
        bool: True if the request is from a tablet, False otherwise
    """
    if not user_agent_string:
        return False
        
    # Basic tablet detection - look for iPad or Android without Mobile
    is_ipad = bool(re.search(r'iPad', user_agent_string))
    is_android_tablet = bool(re.search(r'Android', user_agent_string) and not re.search(r'Mobile', user_agent_string))
    
    return is_ipad or is_android_tablet

def get_device_type(request):
    """
    Determines the device type for a request.
    
    Args:
        request: Flask request object
        
    Returns:
        str: 'mobile', 'tablet', or 'desktop'
    """
    user_agent = request.headers.get('User-Agent', '')
    
    # Check for override parameter (useful for testing)
    force_device = request.args.get('device')
    if force_device in ['mobile', 'tablet', 'desktop']:
        return force_device
    
    # Query parameter override for forcing mobile view
    if request.args.get('mobile') == '1':
        return 'mobile'
    
    # Check for mobile-specific cookie preference
    if request.cookies.get('preferred_view') == 'mobile':
        return 'mobile'
    
    # Detect based on user agent
    if is_tablet(user_agent):
        return 'tablet'
    elif is_mobile(user_agent):
        return 'mobile'
    else:
        return 'desktop' 